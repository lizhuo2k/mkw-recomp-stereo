"""并行调用 inject_stereo_spv 的注入逻辑，处理整目录 .spv。"""
import multiprocessing as mp
import pathlib
import struct
import subprocess
import sys

sys.path.insert(0, "/tmp")
import inject_stereo_spv as M  # noqa: E402

SRC = pathlib.Path(sys.argv[1])
DST = pathlib.Path(sys.argv[2])
JOBS = int(sys.argv[3]) if len(sys.argv) > 3 else 6
DST.mkdir(parents=True, exist_ok=True)


def work(path):
    f = pathlib.Path(path)
    out = DST / f.name
    if out.exists():
        return "cached"
    asm = DST / (f.stem + ".tmp.spvasm")
    try:
        r = subprocess.run(["spirv-dis", str(f), "-o", str(asm)], capture_output=True, text=True)
        if r.returncode != 0:
            return "dis_fail"
        text = asm.read_text()
        bound = struct.unpack("<I", f.read_bytes()[12:16])[0]
        new, why = M.inject(text, bound)
        if not new:
            return "skip:" + why
        asm.write_text(new)
        r = subprocess.run(["spirv-as", str(asm), "-o", str(out), "--target-env", "vulkan1.3"],
                           capture_output=True, text=True)
        if r.returncode != 0:
            out.unlink(missing_ok=True)
            return "as_fail"
        r = subprocess.run(["spirv-val", str(out), "--target-env", "vulkan1.3"], capture_output=True, text=True)
        if r.returncode != 0:
            out.unlink(missing_ok=True)
            return "val_fail:" + r.stderr.strip().split("\n")[0][:70]
        return "ok"
    except Exception as e:  # noqa: BLE001
        return "exc:" + str(e)[:60]
    finally:
        asm.unlink(missing_ok=True)


if __name__ == "__main__":
    files = [str(p) for p in sorted(SRC.glob("*.spv"))]
    print("待处理", len(files))
    from collections import Counter
    c = Counter()
    with mp.Pool(JOBS) as pool:
        for i, res in enumerate(pool.imap_unordered(work, files, chunksize=16), 1):
            c[res.split(":")[0]] += 1
            if res.startswith(("val_fail", "exc", "as_fail")):
                c["! " + res] += 1
            if i % 2000 == 0:
                print("  %d/%d %s" % (i, len(files), dict(c)), flush=True)
    print("结果:", dict(c))
