"""Synthetic schema and CLI rejection tests; no vendor models or inference."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

TOOL = Path(__file__).resolve().parents[1] / "validate_models.py"
spec = importlib.util.spec_from_file_location("public_model_structure", TOOL)
tool = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tool)
AVAILABLE = importlib.util.find_spec("tflite") is not None and importlib.util.find_spec("flatbuffers") is not None


def fixture(buffer_index=0, graph_output=0):
    import flatbuffers
    import tflite
    builder = flatbuffers.Builder(512)
    tflite.BufferStart(builder)
    buffer = tflite.BufferEnd(builder)
    tflite.TensorStart(builder)
    tflite.TensorAddBuffer(builder, buffer_index)
    tensor = tflite.TensorEnd(builder)
    tflite.SubGraphStartTensorsVector(builder, 1)
    builder.PrependUOffsetTRelative(tensor)
    tensors = builder.EndVector()
    tflite.SubGraphStartOutputsVector(builder, 1)
    builder.PrependInt32(graph_output)
    outputs = builder.EndVector()
    tflite.SubGraphStart(builder)
    tflite.SubGraphAddTensors(builder, tensors)
    tflite.SubGraphAddOutputs(builder, outputs)
    graph = tflite.SubGraphEnd(builder)
    tflite.ModelStartSubgraphsVector(builder, 1)
    builder.PrependUOffsetTRelative(graph)
    graphs = builder.EndVector()
    tflite.ModelStartBuffersVector(builder, 1)
    builder.PrependUOffsetTRelative(buffer)
    buffers = builder.EndVector()
    tflite.ModelStart(builder)
    tflite.ModelAddVersion(builder, 3)
    tflite.ModelAddSubgraphs(builder, graphs)
    tflite.ModelAddBuffers(builder, buffers)
    model = tflite.ModelEnd(builder)
    builder.Finish(model, file_identifier=b"TFL3")
    return bytes(builder.Output())


@unittest.skipUnless(AVAILABLE, "optional tflite and flatbuffers schema dependencies not installed")
class ModelStructureTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="x2d-model-schema-")
        self.root = Path(self.temp.name)
        self.inputs = self.root / "inputs"
        self.inputs.mkdir()

    def tearDown(self):
        self.temp.cleanup()

    def write(self, data):
        path = self.inputs / "synthetic.tflite"
        path.write_bytes(data)
        return path

    def run_cli(self, output):
        return subprocess.run([sys.executable, "-B", str(TOOL), "--input", str(self.inputs),
                               "--output", str(output)], capture_output=True, text=True)

    def test_valid_schema_without_exported_tensor_names(self):
        path = self.write(fixture())
        result = tool.inspect_model(path, self.inputs)
        self.assertEqual(result["buffers"], 1)
        self.assertEqual(result["subgraphs"][0]["tensors"], 1)
        self.assertNotIn(str(self.root), json.dumps(result))
        self.assertNotIn("weights", result)

    def test_invalid_tensor_buffer_rejected(self):
        path = self.write(fixture(buffer_index=2))
        with self.assertRaisesRegex(ValueError, "buffer index"):
            tool.inspect_model(path, self.inputs)

    def test_invalid_graph_output_rejected(self):
        path = self.write(fixture(graph_output=7))
        with self.assertRaisesRegex(ValueError, "graph tensor index"):
            tool.inspect_model(path, self.inputs)

    def test_invalid_identifier_rejected(self):
        path = self.write(b"not-a-model")
        with self.assertRaisesRegex(ValueError, "not a TFLite"):
            tool.inspect_model(path, self.inputs)

    def test_existing_output_preserved(self):
        self.write(fixture())
        output = self.root / "summary.json"
        output.write_text("preserved")
        self.assertNotEqual(self.run_cli(output).returncode, 0)
        self.assertEqual(output.read_text(), "preserved")

    def test_output_in_input_tree_rejected(self):
        self.write(fixture())
        output = self.inputs / "summary.json"
        self.assertNotEqual(self.run_cli(output).returncode, 0)
        self.assertFalse(output.exists())

    def test_symlink_model_rejected(self):
        path = self.root / "outside.tflite"
        path.write_bytes(fixture())
        (self.inputs / "linked.tflite").symlink_to(path)
        output = self.root / "summary.json"
        self.assertNotEqual(self.run_cli(output).returncode, 0)
        self.assertFalse(output.exists())

    def test_no_models_rejected(self):
        output = self.root / "summary.json"
        self.assertNotEqual(self.run_cli(output).returncode, 0)
        self.assertFalse(output.exists())

    def test_cli_success_does_not_modify_model(self):
        data = fixture()
        path = self.write(data)
        output = self.root / "summary.json"
        completed = self.run_cli(output)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(path.read_bytes(), data)
        self.assertEqual(json.loads(output.read_text())[0]["file"], "synthetic.tflite")


if __name__ == "__main__":
    unittest.main()
