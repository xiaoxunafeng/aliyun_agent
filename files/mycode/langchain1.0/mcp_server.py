from mcp.server.fastmcp import FastMCP

# 创建 MCP 服务器实例
mcp = FastMCP("MathServer")

@mcp.tool()
def add(a: float, b: float) -> float:
    """计算两个数的和"""
    return a + b +3

@mcp.tool()
def multiply(a: float, b: float) -> float:
    """计算两个数的乘积"""
    return a * b

@mcp.tool()
def power(base: float, exponent: float) -> float:
    """计算幂运算"""
    return base  ** exponent

if __name__ == "__main__":
    # 启动服务器，使用 stdio 传输
    mcp.run(transport="stdio")