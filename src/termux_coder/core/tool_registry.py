class ToolRegistry:
    def __init__(self):
        self.tools = {}

    def register(self, schema, handler):
        name = schema["function"]["name"]
        self.tools[name] = {
            "schema": schema,
            "handler": handler,
        }

    def schemas(self):
        return [tool["schema"] for tool in self.tools.values()]

    async def execute(self, name, args, emit):
        tool = self.tools.get(name)
        if not tool:
            return f"Unknown tool: {name}"

        handler = tool["handler"]
        return await handler(args, emit)
