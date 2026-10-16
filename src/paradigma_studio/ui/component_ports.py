"""Forward explicitly declared attributes to their owning component."""


class component_attribute:
    def __init__(self, component: str, name: str | None = None):
        self.component, self.name = component, name

    def __set_name__(self, owner, name):
        if self.name is None:
            self.name = name

    def __get__(self, owner, cls=None):
        if owner is None:
            return self
        return getattr(getattr(owner, self.component), self.name)

    def __set__(self, owner, value):
        setattr(getattr(owner, self.component), self.name, value)

    def __call__(self, owner, *args, **kwargs):
        return self.__get__(owner)(*args, **kwargs)
