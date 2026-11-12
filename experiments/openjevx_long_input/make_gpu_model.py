"""Make a GPU-friendly copy of openjevx.w8.onnx for the simulations (the original stays untouched).

The released graph stores weights as int8 -> DequantizeLinear -> MatMul. On CPU, onnxruntime fuses that
into 8-bit kernels; on CUDA it re-dequantizes all 120 weight tensors on every call. Here we fold every
DequantizeLinear whose inputs are constants into a plain float initializer (bit-identical weights), then
optionally convert to fp16 for tensor cores (keeping inputs/outputs and LayerNorm/Softmax in fp32).

    python make_gpu_model.py            # writes models/openjevx_gpu/openjevx.fp32.onnx and .fp16.onnx
"""
import os
import shutil

import numpy as np
import onnx
from onnx import numpy_helper

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "..", "models", "openjevx")
DST = os.path.join(HERE, "..", "models", "openjevx_gpu")


def fold_dequant(model):
    g = model.graph
    inits = {i.name: i for i in g.initializer}
    consts = {}
    for n in g.node:  # Constant nodes are constants too
        if n.op_type == "Constant" and len(n.output) == 1:
            for a in n.attribute:
                if a.name == "value":
                    consts[n.output[0]] = numpy_helper.to_array(a.t)
    keep, new_inits, folded = [], [], 0
    for n in g.node:
        if n.op_type == "DequantizeLinear" and all(i in inits or i in consts or i == "" for i in n.input):
            def arr(name):
                return numpy_helper.to_array(inits[name]) if name in inits else consts[name]
            x = arr(n.input[0]).astype(np.float32)
            scale = arr(n.input[1]).astype(np.float32)
            zp = arr(n.input[2]).astype(np.float32) if len(n.input) > 2 and n.input[2] else np.zeros_like(scale)
            axis = 1
            for a in n.attribute:
                if a.name == "axis":
                    axis = a.i
            if scale.ndim == 0 or scale.size == 1:
                w = (x - zp) * scale
            else:  # per-channel along `axis`
                shape = [1] * x.ndim
                shape[axis] = -1
                w = (x - zp.reshape(shape)) * scale.reshape(shape)
            new_inits.append(numpy_helper.from_array(w.astype(np.float32), n.output[0]))
            folded += 1
        else:
            keep.append(n)
    del g.node[:]
    g.node.extend(keep)
    g.initializer.extend(new_inits)
    # drop initializers nobody uses any more
    used = {i for n in g.node for i in n.input} | {o.name for o in g.output}
    alive = [i for i in g.initializer if i.name in used]
    del g.initializer[:]
    g.initializer.extend(alive)
    return folded


def main():
    os.makedirs(DST, exist_ok=True)
    for f in ("tokenizer.json", "config.json"):
        shutil.copy(os.path.join(SRC, f), os.path.join(DST, f))
    m = onnx.load(os.path.join(SRC, "openjevx.w8.onnx"))
    print("folded", fold_dequant(m), "DequantizeLinear nodes")
    onnx.save(m, os.path.join(DST, "openjevx.fp32.onnx"), save_as_external_data=True, all_tensors_to_one_file=True,
              location="openjevx.fp32.onnx.data")
    from onnxruntime.transformers.float16 import convert_float_to_float16
    m16 = convert_float_to_float16(m, keep_io_types=True, op_block_list=["LayerNormalization", "Softmax", "Erf"])
    onnx.save(m16, os.path.join(DST, "openjevx.fp16.onnx"), save_as_external_data=True, all_tensors_to_one_file=True,
              location="openjevx.fp16.onnx.data")
    print("wrote", os.listdir(DST))


if __name__ == "__main__":
    main()
