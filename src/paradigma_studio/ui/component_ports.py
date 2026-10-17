"""Forward explicitly declared attributes to their owning component."""

from typing import Any, cast


class component_attribute:
    # Each declared port can carry a widget, action or state owned by its component.
    def __init__(self, component: str, name: str | None = None) -> None:
        self.component, self.name = component, name

    def __set_name__(self, owner: type, name: str) -> None:
        if self.name is None:
            self.name = name

    def __get__(self, owner: Any, cls: type | None = None) -> Any:
        if owner is None:
            return self
        # Python calls __set_name__ before a declared descriptor can be accessed.
        return getattr(getattr(owner, self.component), cast(str, self.name))

    def __set__(self, owner: Any, value: Any) -> None:
        setattr(getattr(owner, self.component), cast(str, self.name), value)

    def __call__(self, owner: Any, *args: Any, **kwargs: Any) -> Any:
        return self.__get__(owner)(*args, **kwargs)
