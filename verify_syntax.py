import py_compile
import sys

files_to_check = ['main.py', 'ai_engine.py', 'decorators.py', 'forms.py', 'api/index.py']
success = True

print("Checking files for syntax errors...")
for filename in files_to_check:
    try:
        py_compile.compile(filename, doraise=True)
        print(f"  [OK] {filename} compiled successfully.")
    except py_compile.PyCompileError as e:
        print(f"  [ERROR] Syntax error in {filename}:")
        print(e)
        success = False

if success:
    print("All python files compiled successfully without syntax errors!")
    sys.exit(0)
else:
    print("Syntax checks failed.")
    sys.exit(1)
