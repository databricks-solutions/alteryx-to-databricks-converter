"""XML parsing utility functions."""

from __future__ import annotations

from lxml import etree


def get_text(element: etree._Element | None, default: str = "") -> str:
    """Get text content of an element, or default if None."""
    if element is None:
        return default
    return element.text or default


def get_attr(element: etree._Element, name: str, default: str = "") -> str:
    """Get attribute value from element."""
    return element.get(name, default)


def get_child_text(parent: etree._Element, tag: str, default: str = "") -> str:
    """Get text of a child element by tag name."""
    child = parent.find(tag)
    return get_text(child, default)


def get_child_attr(parent: etree._Element, child_tag: str, attr: str, default: str = "") -> str:
    """Get attribute of a child element."""
    child = parent.find(child_tag)
    if child is None:
        return default
    return get_attr(child, attr, default)


def element_to_dict(element: etree._Element) -> dict:
    """Recursively convert an XML element to a nested dict.

    Attributes are stored with '@' prefix. Text content stored as '#text'.
    Repeated child tags become lists.
    """
    result: dict = {}

    # Add attributes
    for key, value in element.attrib.items():
        result[f"@{key}"] = value

    # Add text content
    if element.text and element.text.strip():
        if len(element) == 0 and not result:
            return element.text.strip()
        result["#text"] = element.text.strip()

    # Add children
    for child in element:
        child_data = element_to_dict(child)
        tag = child.tag
        if tag in result:
            # Convert to list if multiple same-tag children
            existing = result[tag]
            if not isinstance(existing, list):
                result[tag] = [existing]
            result[tag].append(child_data)
        else:
            result[tag] = child_data

    return result


def find_all_recursive(element: etree._Element, tag: str) -> list[etree._Element]:
    """Find all descendants with given tag (recursive)."""
    return element.findall(f".//{tag}")
