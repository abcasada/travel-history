"""A minimal Mapbox Vector Tile (protobuf) decoder for tests: layers, features, properties and
point coordinates. Enough to count what a tile reveals without adding a dependency."""

from __future__ import annotations

import struct
from dataclasses import dataclass, field


def _varint(buf: bytes, i: int) -> tuple[int, int]:
    shift = result = 0
    while True:
        b = buf[i]
        i += 1
        result |= (b & 0x7F) << shift
        if not b & 0x80:
            return result, i
        shift += 7


def _fields(buf: bytes):
    """Yield (field number, wire type, value) for one protobuf message."""
    i = 0
    while i < len(buf):
        key, i = _varint(buf, i)
        number, wire = key >> 3, key & 7
        if wire == 0:
            value, i = _varint(buf, i)
        elif wire == 1:
            value, i = buf[i : i + 8], i + 8
        elif wire == 2:
            length, i = _varint(buf, i)
            value, i = buf[i : i + length], i + length
        elif wire == 5:
            value, i = buf[i : i + 4], i + 4
        else:
            raise ValueError(f"unsupported wire type {wire}")
        yield number, wire, value


def _packed(buf: bytes) -> list[int]:
    out, i = [], 0
    while i < len(buf):
        value, i = _varint(buf, i)
        out.append(value)
    return out


def _zigzag(n: int) -> int:
    return (n >> 1) ^ -(n & 1)


def _value(buf: bytes):
    for number, _wire, value in _fields(buf):
        if number == 1:
            return value.decode()
        if number == 2:
            return struct.unpack("<f", value)[0]
        if number == 3:
            return struct.unpack("<d", value)[0]
        if number in (4, 5):
            return value if number == 5 or value < 2**63 else value - 2**64
        if number == 6:
            return _zigzag(value)
        if number == 7:
            return bool(value)
    return None


@dataclass
class Feature:
    type: int  # 1 point, 2 line, 3 polygon
    properties: dict
    commands: list[int]

    def points(self) -> list[tuple[int, int]]:
        """Absolute tile coordinates of every vertex."""
        out, x, y, i = [], 0, 0, 0
        while i < len(self.commands):
            command, count = self.commands[i] & 7, self.commands[i] >> 3
            i += 1
            if command == 7:  # ClosePath
                continue
            for _ in range(count):
                x += _zigzag(self.commands[i])
                y += _zigzag(self.commands[i + 1])
                i += 2
                out.append((x, y))
        return out


@dataclass
class Layer:
    name: str = ""
    extent: int = 4096
    features: list[Feature] = field(default_factory=list)


def decode(data: bytes) -> dict[str, Layer]:
    layers = {}
    for number, _wire, raw_layer in _fields(data):
        if number != 3:
            continue
        layer, keys, values, raw_features = Layer(), [], [], []
        for n, _w, v in _fields(raw_layer):
            if n == 1:
                layer.name = v.decode()
            elif n == 2:
                raw_features.append(v)
            elif n == 3:
                keys.append(v.decode())
            elif n == 4:
                values.append(_value(v))
            elif n == 5:
                layer.extent = v
        for raw in raw_features:
            tags, geom_type, commands = [], 0, []
            for n, _w, v in _fields(raw):
                if n == 2:
                    tags = _packed(v)
                elif n == 3:
                    geom_type = v
                elif n == 4:
                    commands = _packed(v)
            props = {keys[tags[k]]: values[tags[k + 1]] for k in range(0, len(tags), 2)}
            layer.features.append(Feature(geom_type, props, commands))
        layers[layer.name] = layer
    return layers
