import ast
import math
import operator

OPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
       ast.Div: operator.truediv, ast.Pow: operator.pow, ast.Mod: operator.mod}


def safe_calculate(expression: str) -> float | int:
    """A bounded numerical AST evaluator. Never eval, exec, imports or attributes."""
    if len(expression) > 200:
        raise ValueError("Biểu thức quá dài")
    tree = ast.parse(expression, mode="eval")
    if sum(1 for _ in ast.walk(tree)) > 60:
        raise ValueError("Biểu thức quá phức tạp")

    def evaluate(node):
        if isinstance(node, ast.Expression):
            return evaluate(node.body)
        if isinstance(node, ast.Constant) and type(node.value) in (int, float):
            value = node.value
        elif isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            value = evaluate(node.operand) * (-1 if isinstance(node.op, ast.USub) else 1)
        elif isinstance(node, ast.BinOp) and type(node.op) in OPS:
            left, right = evaluate(node.left), evaluate(node.right)
            if isinstance(node.op, ast.Pow) and (abs(right) > 10 or abs(left) > 1e6):
                raise ValueError("Lũy thừa vượt giới hạn")
            value = OPS[type(node.op)](left, right)
        else:
            raise ValueError("Chỉ cho phép phép tính số học")
        if isinstance(value, complex) or not math.isfinite(value) or abs(value) > 1e15:
            raise ValueError("Kết quả vượt giới hạn")
        return value

    try:
        res = evaluate(tree)
        if isinstance(res, float):
            res = round(res, 10)
            if res.is_integer():
                res = int(res)
        return res
    except (ZeroDivisionError, OverflowError) as exc:
        raise ValueError("Phép tính không hợp lệ") from exc
