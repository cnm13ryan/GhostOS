from os.path import join, abspath, dirname
import argparse
import os
import shutil
import sys

demo_dir = join(dirname(dirname(__file__)), 'demo')


def main():
    parser = argparse.ArgumentParser(
        description="initialize GhostOS skeleton files to target directory",
    )
    parser.add_argument(
        "--target", "-t",
        help="the target directory that keep the skeleton files of GhostOS",
        type=str,
        required=True,
    )
    parsed = parser.parse_args(sys.argv[1:])
    target_dir = abspath(parsed.target)

    # the codes below are generated by gpt-4o
    # Copy files from demo_dir to target_dir
    if not os.path.exists(target_dir):
        os.makedirs(target_dir)
    for item in os.listdir(demo_dir):
        s = os.path.join(demo_dir, item)
        d = os.path.join(target_dir, item)
        if "__pycache__" in s:
            continue
        if os.path.isdir(s):
            shutil.copytree(s, d, False, None)
        else:
            shutil.copy2(s, d)
    print(f"Copied skeleton files to {target_dir}")


# if __name__ == '__main__':
#     from ghostos.prototypes.console import new_console_app
#     from ghostos.thoughts import new_file_editor_thought
#
#     app = new_console_app(demo_dir, 0)
#     app.run_thought(
#         new_file_editor_thought(filepath=__file__),
#         instruction="help me to complete the main func."
#     )

if __name__ == '__main__':
    main()