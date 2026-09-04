import ast
import operator
from typing import Any

from app.tools.base import BaseTool, ToolResult

_BINARY_OPERATORS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}
_UNARY_OPERATORS = {ast.UAdd: operator.pos, ast.USub: operator.neg}


class PythonRunnerTool(BaseTool):
    name = "python_runner"
    description = "Evaluates a restricted numeric expression; no imports, names, or I/O."

    async def execute(self, **kwargs: Any) -> ToolResult:
        try:
            expression = str(kwargs["expression"])
            if len(expression) > 200:
                raise ValueError("Expression is too long")
            value = self._evaluate(ast.parse(expression, mode="eval").body)
            return ToolResult(success=True, output=value)
        except Exception as exc:
            return ToolResult(success=False, error=str(exc))

    def _evaluate(self, node: ast.AST) -> int | float:
        if isinstance(node, ast.Constant) and type(node.value) in (int, float):
            return node.value
        if isinstance(node, ast.BinOp) and type(node.op) in _BINARY_OPERATORS:
            left = self._evaluate(node.left)
            right = self._evaluate(node.right)
            if isinstance(node.op, ast.Pow) and abs(right) > 10:
                raise ValueError("Exponent is outside the safe range")
            return _BINARY_OPERATORS[type(node.op)](left, right)
        if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY_OPERATORS:
            return _UNARY_OPERATORS[type(node.op)](self._evaluate(node.operand))
        raise ValueError("Only basic numeric expressions are allowed")
