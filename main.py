"""
这个文件是整个项目的"程序入口"。

经过重构后，它不再负责具体的调度逻辑，
而是把"运行一个 PixivApp"这件事交给 app/application.py 中的 PixivApplication 类。

你现在看到的就是最终形态：main.py 只做三件事：
1. 创建 PixivApplication 实例
2. 调用 run() 方法
3. 将返回值传给 sys.exit()
"""

import sys

from app.application import PixivApplication
def main(argv: list[str] | None = None) -> int | None:
    """
    主函数。

    它现在只做调度，不做具体实现。
    所有动作分发、资源管理都交给 PixivApplication。
    """
    with PixivApplication() as app:
        return app.run(argv)
if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
