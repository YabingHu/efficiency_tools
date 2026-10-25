"""在独立子进程中加载中文引擎及项目内的固定版本兼容层。"""
import importlib
import runpy
import sys
from pathlib import Path


def main():
    engine = Path(sys.argv[1]).resolve()
    if engine.name != "last30days.py" or not (engine.parent / "lib").is_dir():
        raise ValueError("中文引擎入口无效")
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    sys.path.insert(0, str(engine.parent))
    from src.collectors.cn_engine_compat import install

    install(*(importlib.import_module(f"lib.{name}") for name in ("weibo", "toutiao", "zhihu")))
    sys.argv = [str(engine), *sys.argv[2:]]
    runpy.run_path(str(engine), run_name="__main__")


if __name__ == "__main__":
    main()
