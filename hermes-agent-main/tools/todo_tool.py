"""
tools/todo_tool.py — Todo Tool Injector & Store
"""

TODO_INJECTION_HEADER = "### Active TODO Items ###\n"


class TodoStore:
    def __init__(self, *args, **kwargs):
        self.todos = []

    def get_todos(self):
        return self.todos

    def add_todo(self, item):
        self.todos.append(item)
