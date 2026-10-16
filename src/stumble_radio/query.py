"""Small field:value queries shared by the search bar and advanced form."""

import json
import shlex
from dataclasses import replace

from .models import SORTS, Search

ALIASES = {
    "county": "country",
    "countrycode": "country",
    "region": "state",
    "city": "state",
    "lang": "language",
    "tag": "tags",
    "genre": "tags",
    "genres": "tags",
    "minbitrate": "bitrate_min",
    "maxbitrate": "bitrate_max",
    "order": "sort",
    "dir": "direction",
    "latitude": "lat",
    "longitude": "lon",
    "radius_km": "radius",
    "taglist": "tags",
    "bitratemin": "bitrate_min",
    "bitratemax": "bitrate_max",
    "https_only": "https",
    "descending": "reverse",
}


def split_query(text: str, *, operators: bool = False) -> list[str]:
    lexer = shlex.shlex(text, posix=True, punctuation_chars="|+()" if operators else False)
    lexer.whitespace_split = True
    lexer.commenters = ""
    # Apostrophes are common in station names; only double quotes delimit phrases.
    lexer.quotes = '"'
    try:
        return list(lexer)
    except ValueError as error:
        raise ValueError("Close the double quote around your phrase.") from error


def search_from_tokens(tokens: list[str]) -> Search:
    values, terms, tags, seen = {}, [], [], set()
    for token in tokens:
        if ":" not in token:
            terms.append(token)
            continue
        key, value = token.split(":", 1)
        key = ALIASES.get(key.casefold(), key.casefold())
        value = value.strip()
        if not value:
            raise ValueError(f"Add a value after {key}:")
        if key in seen and key not in {"tags", "text"}:
            raise ValueError(f"Use {key}: only once.")
        seen.add(key)
        if key == "text":
            terms.append(value)
        elif key == "tags":
            tags.extend(t.strip() for t in value.split(",") if t.strip())
        elif key in {"name", "country", "state", "language", "codec"}:
            values[key] = value
        elif key in {"bitrate_min", "bitrate_max", "bitrate"}:
            try:
                if key == "bitrate":
                    low, separator, high = value.partition("..")
                    bounds = {
                        "bitrate_min": int(low or "0"),
                        "bitrate_max": int(high or "0") if separator else int(low),
                    }
                else:
                    bounds = {key: int(value)}
                Search(**bounds)
                for bound, amount in bounds.items():
                    previous = values.get(bound, 0)
                    values[bound] = (
                        max(previous, amount)
                        if bound == "bitrate_min"
                        else (min(previous, amount) if previous and amount else previous or amount)
                    )
            except ValueError as error:
                raise ValueError(f"Use {key}:128 or bitrate:128..320 (kbps).") from error
        elif key in {"https", "broken", "hidebroken", "reverse"}:
            boolean = {
                "true": True,
                "false": False,
                "yes": True,
                "no": False,
                "1": True,
                "0": False,
            }.get(value.casefold())
            if boolean is None:
                raise ValueError(f"Use {key}:true or {key}:false.")
            target = {
                "https": "https_only",
                "broken": "hidebroken",
                "hidebroken": "hidebroken",
                "reverse": "descending",
            }[key]
            values[target] = not boolean if key == "broken" else boolean
        elif key == "sort":
            order = {
                "plays": "clickcount",
                "clicks": "clickcount",
                "genre": "tags",
                "favorites": "favourite",
                "favourites": "favourite",
                "star": "favourite",
            }.get(value.casefold(), value.casefold())
            if order not in SORTS:
                raise ValueError(
                    "Sort by plays, votes, name, country, genre, bitrate, favourites, "
                    "recent or listen."
                )
            values["order"] = order
        elif key == "direction":
            if value.casefold() not in {"asc", "desc"}:
                raise ValueError("Use direction:asc or direction:desc.")
            values["descending"] = value.casefold() == "desc"
        elif key in {"lat", "lon", "radius", "near"}:
            try:
                if key == "near":
                    latitude, longitude, radius = map(float, value.split(","))
                    values.update(latitude=latitude, longitude=longitude, radius_km=radius)
                else:
                    values[{"lat": "latitude", "lon": "longitude", "radius": "radius_km"}[key]] = (
                        float(value)
                    )
            except ValueError as error:
                raise ValueError("Use near:LAT,LON,RADIUS_KM or lat:… lon:… radius:…") from error
        else:
            raise ValueError(f"Unknown filter '{key}'. Try country:, genre:, language: or name:.")
    if values.get("order") in {"name", "country", "tags"} and "descending" not in values:
        values["descending"] = False
    return Search(terms=tuple(terms), tags=",".join(dict.fromkeys(tags)), **values)


def combine(operator: str, nodes: list[tuple]) -> tuple:
    return (operator, *nodes) if len(nodes) > 1 else nodes[0] if nodes else ()


class _ExpressionParser:
    def __init__(self, text: str):
        if len(text) > 4096:
            raise ValueError("Keep the search query under 4096 characters.")
        self.tokens = []
        for token in split_query(text, operators=True):
            if not token:
                continue
            self.tokens.extend(token if token and all(c in "|+()" for c in token) else [token])
        if len(self.tokens) > 128:
            raise ValueError("Use a shorter query (at most 128 tokens).")
        self.position = 0
        self.depth = 0

    def peek(self):
        return self.tokens[self.position] if self.position < len(self.tokens) else None

    def sequence(self):
        nodes = [self.either()]
        while self.peek() is not None and self.peek() != ")":
            nodes.append(self.either())
        return combine("and", nodes)

    def either(self):
        nodes = [self.both()]
        while self.peek() == "|":
            self.position += 1
            nodes.append(self.both())
        return combine("or", nodes)

    def both(self):
        nodes = [self.atom()]
        while self.peek() == "+":
            self.position += 1
            nodes.append(self.atom())
        return combine("and", nodes)

    def atom(self):
        token = self.peek()
        if token is None or token in {"|", "+", ")"}:
            raise ValueError("Add a word, filter or group on each side of | and +.")
        self.position += 1
        if token == "(":
            self.depth += 1
            if self.depth > 16:
                raise ValueError("Use at most 16 levels of parentheses.")
            node = self.sequence()
            if self.peek() != ")":
                raise ValueError("Close the parenthesis around your group.")
            self.position += 1
            self.depth -= 1
            return node
        return ("leaf", token)


def parse_expression(text: str) -> tuple:
    parser = _ExpressionParser(text)
    if not parser.tokens:
        return ()
    node = parser.sequence()
    if parser.peek() is not None:
        raise ValueError("Unexpected closing parenthesis.")
    return node


def _clauses(node: tuple):
    if node and node[0] == "and":
        for child in node[1:]:
            yield from _clauses(child)
    elif node:
        yield node


def validate_expression(node: tuple):
    if node[0] == "leaf":
        key = node[1].partition(":")[0].casefold()
        if ":" in node[1] and ALIASES.get(key, key) in {
            "sort",
            "direction",
            "broken",
            "hidebroken",
            "reverse",
            "lat",
            "lon",
            "radius",
        }:
            raise ValueError(
                f"Use {key}: as a separate clause; use near: for grouped location filters."
            )
        search_from_tokens([node[1]])
    else:
        for child in node[1:]:
            validate_expression(child)


def parse_query(text: str) -> Search:
    tokens, expressions = [], []
    for node in _clauses(parse_expression(text)):
        if node[0] == "leaf":
            tokens.append(node[1])
        else:
            validate_expression(node)
            expressions.append(node)
    search = search_from_tokens(tokens)
    return replace(search, expression=combine("and", expressions))


def quote_value(value: str) -> str:
    return (
        json.dumps(value, ensure_ascii=False)
        if any(c.isspace() or c in '\\"|+()' for c in value)
        else value
    )


def format_expression(node: tuple) -> str:
    if not node:
        return ""
    if node[0] == "leaf":
        key, separator, value = node[1].partition(":")
        return key + ":" + quote_value(value) if separator else quote_value(key)
    connector = "|" if node[0] == "or" else "+"
    return "(" + connector.join(format_expression(child) for child in node[1:]) + ")"


def format_query(search: Search) -> str:
    tokens = [("text:" if ":" in term else "") + quote_value(term) for term in search.terms]
    if search.expression:
        tokens.insert(0, format_expression(search.expression))
    for key in ("name", "country", "state", "language", "tags", "codec"):
        if value := getattr(search, key):
            tokens.append(f"{key}:{quote_value(value)}")
    if search.bitrate_min or search.bitrate_max:
        tokens.append(f"bitrate:{search.bitrate_min}..{search.bitrate_max or ''}")
    if search.https_only:
        tokens.append("https:true")
    if not search.hidebroken:
        tokens.append("broken:true")
    if search.latitude is not None:
        tokens.append(f"near:{search.latitude},{search.longitude},{search.radius_km}")
    if search.order != "clickcount":
        tokens.append(f"sort:{search.order}")
    if search.descending != (search.order not in {"name", "country", "tags"}):
        tokens.append(f"direction:{'desc' if search.descending else 'asc'}")
    return " ".join(tokens)
