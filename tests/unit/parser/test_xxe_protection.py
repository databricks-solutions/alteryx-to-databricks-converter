"""XXE regression guard for the workflow parser.

Protection is already in place (``resolve_entities=False, no_network=True``) but
nothing pinned it, so a future parser refactor could quietly remove it. The
parser is the one component that consumes fully untrusted input — uploaded .yxmd
files — so this is worth a dedicated test.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from a2d.parser.workflow_parser import WorkflowParser

# A local file an XXE payload would try to exfiltrate. Present on every POSIX box
# and readable, so a successful attack would visibly leak "root:".
SENSITIVE_FILE = "/etc/passwd"

XXE_FILE_READ = f"""<?xml version="1.0"?>
<!DOCTYPE foo [<!ENTITY xxe SYSTEM "file://{SENSITIVE_FILE}">]>
<AlteryxDocument yxmdVer="2023.1">
  <Nodes>
    <Node ToolID="1">
      <GuiSettings Plugin="AlteryxBasePluginsGui.DbFileInput.DbFileInput">
        <Position x="1" y="1"/>
      </GuiSettings>
      <Properties>
        <Configuration><File FileFormat="19" FilePath="&xxe;"/></Configuration>
        <Annotation><Name>&xxe;</Name></Annotation>
      </Properties>
    </Node>
  </Nodes>
  <Connections/>
</AlteryxDocument>
"""

# "Billion laughs" — nested entity expansion aimed at exhausting memory.
XXE_BILLION_LAUGHS = """<?xml version="1.0"?>
<!DOCTYPE lolz [
  <!ENTITY lol "lol">
  <!ENTITY lol1 "&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;">
  <!ENTITY lol2 "&lol1;&lol1;&lol1;&lol1;&lol1;&lol1;&lol1;&lol1;&lol1;&lol1;">
  <!ENTITY lol3 "&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;">
]>
<AlteryxDocument yxmdVer="2023.1">
  <Nodes>
    <Node ToolID="1">
      <GuiSettings Plugin="AlteryxBasePluginsGui.DbFileInput.DbFileInput"/>
      <Properties><Annotation><Name>&lol3;</Name></Annotation></Properties>
    </Node>
  </Nodes>
  <Connections/>
</AlteryxDocument>
"""

# Remote entity: must never cause a network fetch.
XXE_REMOTE = """<?xml version="1.0"?>
<!DOCTYPE foo [<!ENTITY xxe SYSTEM "http://169.254.169.254/latest/meta-data/">]>
<AlteryxDocument yxmdVer="2023.1">
  <Nodes>
    <Node ToolID="1">
      <GuiSettings Plugin="AlteryxBasePluginsGui.DbFileInput.DbFileInput"/>
      <Properties><Annotation><Name>&xxe;</Name></Annotation></Properties>
    </Node>
  </Nodes>
  <Connections/>
</AlteryxDocument>
"""


def _parse(tmp_path: Path, xml: str):
    path = tmp_path / "payload.yxmd"
    path.write_text(xml)
    return WorkflowParser().parse(path)


def _all_text(workflow) -> str:
    """Every string a payload could have landed in."""
    parts: list[str] = []
    for node in workflow.nodes:
        parts.append(str(node.annotation or ""))
        parts.append(str(node.configuration))
    return " ".join(parts)


@pytest.mark.skipif(
    not Path(SENSITIVE_FILE).exists(),
    reason="needs a readable local file to prove nothing leaked",
)
def test_local_file_entity_is_not_expanded(tmp_path):
    """The classic XXE: a file:// entity must never reach parsed output."""
    try:
        workflow = _parse(tmp_path, XXE_FILE_READ)
    except Exception:
        return  # rejecting the document outright is also a safe outcome

    text = _all_text(workflow)
    assert "root:" not in text, "XXE leaked /etc/passwd into the parsed workflow"
    assert "/bin/" not in text


def test_billion_laughs_does_not_expand(tmp_path):
    """Nested entity expansion must not blow up memory or produce the payload."""
    try:
        workflow = _parse(tmp_path, XXE_BILLION_LAUGHS)
    except Exception:
        return

    text = _all_text(workflow)
    # 'lol' repeated 1000x would appear if entities expanded.
    assert text.count("lol") < 100


def test_remote_entity_is_not_fetched(tmp_path):
    """A remote entity must not trigger a network call (no_network=True)."""
    try:
        workflow = _parse(tmp_path, XXE_REMOTE)
    except Exception:
        return

    text = _all_text(workflow)
    assert "ami-" not in text
    assert "instance-id" not in text


def test_shared_parser_does_not_expand_entities():
    """Assert the shared parser's behaviour, so intent survives a refactor.

    lxml doesn't expose ``resolve_entities`` for reading, so this checks the
    observable effect instead — which is the property we actually care about.
    """
    from lxml import etree

    from a2d.parser.workflow_parser import _SAFE_PARSER

    xml = b'<?xml version="1.0"?><!DOCTYPE d [<!ENTITY e "EXPANDED">]><d>&e;</d>'
    root = etree.fromstring(xml, parser=_SAFE_PARSER)

    assert "EXPANDED" not in (root.text or "")
