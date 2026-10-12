#!/usr/bin/env python3
"""Read-only TFLite v3 schema checks; no decryption, weights export or inference.

Adapted from this project's 2026-10-09 offline model validation. Requires the
external tflite schema package; no vendor model or keys are distributed.
"""
import argparse
import hashlib
import json
from pathlib import Path


def require(condition, message):
    if not condition:
        raise ValueError(message)


def inspect_model(path, root):
    import tflite

    require(path.stat().st_size <= 512 * 1024 * 1024, "model exceeds local inspection limit")
    data = path.read_bytes()
    require(len(data) >= 8 and data[4:8] == b"TFL3", "not a TFLite flatbuffer")
    model = tflite.Model.GetRootAsModel(data, 0)
    require(model.Version() == 3, "unsupported schema version")
    require(model.SubgraphsLength() > 0 and model.BuffersLength() > 0, "empty model tables")
    buffer_count = model.BuffersLength()
    for index in range(buffer_count):
        buffer = model.Buffers(index)
        if buffer.DataLength():
            buffer.Data(0)
            buffer.Data(buffer.DataLength() - 1)
    code_count = model.OperatorCodesLength()
    for index in range(code_count):
        code = model.OperatorCodes(index)
        code.BuiltinCode()
        code.Version()
    graphs = []
    for index in range(model.SubgraphsLength()):
        graph = model.Subgraphs(index)
        count = graph.TensorsLength()
        for tensor_index in range(count):
            tensor = graph.Tensors(tensor_index)
            require(0 <= tensor.Buffer() < buffer_count, "tensor buffer index out of range")
            for axis in range(tensor.ShapeLength()):
                tensor.Shape(axis)
        for field in ("Inputs", "Outputs"):
            for port in range(getattr(graph, field + "Length")()):
                require(0 <= getattr(graph, field)(port) < count, "graph tensor index out of range")
        for operator_index in range(graph.OperatorsLength()):
            operator = graph.Operators(operator_index)
            require(0 <= operator.OpcodeIndex() < code_count, "operator code index out of range")
            for port in range(operator.InputsLength()):
                require(-1 <= operator.Inputs(port) < count, "operator input index out of range")
            for port in range(operator.OutputsLength()):
                require(0 <= operator.Outputs(port) < count, "operator output index out of range")
        graphs.append({"tensors": count, "operators": graph.OperatorsLength(),
                       "inputs": graph.InputsLength(), "outputs": graph.OutputsLength()})
    return {"file": path.relative_to(root).as_posix(), "bytes": len(data),
            "sha256": hashlib.sha256(data).hexdigest(), "schema_version": 3,
            "buffers": buffer_count, "operator_codes": code_count, "subgraphs": graphs,
            "scope": "schema/index inspection only; no inference"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = args.input.resolve(strict=True)
    output = args.output.resolve()
    require(root.is_dir(), "input must be a directory")
    require(output != root and root not in output.parents, "output must be outside the input tree")
    require(not output.exists(), "output must not already exist")
    paths = sorted(root.rglob("*.tflite"))
    require(paths, "no models found")
    require(all(not path.is_symlink() and root in path.resolve().parents for path in paths),
            "model symlinks are not accepted")
    records = [inspect_model(path, root) for path in paths]
    with output.open("x", encoding="utf-8") as stream:
        json.dump(records, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    print(f"STRUCTURE CHECK PASSED: {len(records)} local models; no inference")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
