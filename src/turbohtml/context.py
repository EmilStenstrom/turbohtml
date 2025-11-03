class FragmentContext:
    __slots__ = ("tag_name", "namespace")

    def __init__(self, tag_name, namespace=None):
        self.tag_name = tag_name
        self.namespace = namespace

    def __repr__(self):
        ns = f"{self.namespace}:" if self.namespace else ""
        return f"FragmentContext({ns}{self.tag_name})"
