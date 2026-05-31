"""Root pytest config — load .env before test collection so that variables
like CLANG_PATH are visible when test modules call analyzer helpers at
import time (e.g. the `skipif` decorator in tests/test_llvm_ir.py)."""

from dotenv import load_dotenv

load_dotenv()
