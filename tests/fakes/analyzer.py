"""MDE Client Analyzer results, made up, laid out as the analyzers write them: a Windows
zip (its names with backslashes) and a Linux one, with or without Linux's catalogue."""

import zipfile
from pathlib import Path

# The analyzer writes its guidance as HTML inside the XML's text, so it arrives escaped.
WINDOWS_XML = """<?xml version="1.0" encoding="utf-8"?>
<MDEResults>
  <general>
    <psLanguageMode displayName="PowerShell Language mode: ">
      <value>FullLanguage</value>
    </psLanguageMode>
    <scriptVersion displayName="Script Version: "><value>01Jul2026</value></scriptVersion>
    <scriptRunTime displayName="Script RunTime: "><value>09/27/2026 00:29:59</value></scriptRunTime>
  </general>
  <devInfo>
    <deviceName displayName="Device Host Name"><value>web01</value></deviceName>
    <osName displayName="Device Operating System"><value>Windows Server 2022</value></osName>
  </devInfo>
  <EDRCompInfo>
    <senseStatus displayName="Sense service Status">
      <value>Stopped</value><alert>High</alert>
    </senseStatus>
  </EDRCompInfo>
  <MDEDevConfig/>
  <AVCompInfo>
    <avSig displayName="Defender AV Security Intelligence Version"><value>1.419.1.0</value></avSig>
  </AVCompInfo>
  <events>
    <event id="130017">
      <severity>Informational</severity><category>Connectivity</category>
      <check>EDRCloud CnC</check><checkresult>Connected</checkresult><guidance></guidance>
    </event>
    <event id="121012">
      <severity>Warning</severity><category>Configuration</category>
      <check>SecurityIntelligenceVersion</check>
      <checkresult>Outdated &lt;b&gt;version&lt;/b&gt;</checkresult>
      <guidance>Update it:&lt;br&gt;&lt;a target='_blank'
        href='https://learn.microsoft.com/x'&gt;Updates&lt;/a&gt; &amp;amp; more</guidance>
    </event>
    <event id="122001">
      <severity>Error</severity><category>Services</category>
      <check>SenseService</check><checkresult>Sense is stopped</checkresult><guidance></guidance>
    </event>
  </events>
</MDEResults>
"""

LINUX_XML = """<mdatp>
  <general>
    <script_version>1.5.0</script_version>
    <script_run_time>2026-09-27T00:31:39+00:00</script_run_time>
  </general>
  <device_info>
    <device_name display_name="Device Name">db01</device_name>
    <host_name display_name="Host Name">db01.corp.example</host_name>
    <os_family display_name="OS Family">Linux</os_family>
    <av_signature_version display_name="Defender AV Security Intelligence Version">
      1.419.2.0
    </av_signature_version>
  </device_info>
  <events><event id="330002"/><event id="331004"/><event id="332009"/><event id="339999"/></events>
</mdatp>
"""

MACOS_XML = LINUX_XML.replace(">Linux<", ">Darwin<").replace('"33', '"23')

LINUX_CATALOGUE = """<events>
  <event id="331004"><check_name>EDR Cloud Cyber</check_name><tsg>
    Some test connections failed:
    https://learn.microsoft.com/y
  </tsg></event>
</events>
"""


def write_windows_zip(folder: Path, name: str = "MDEClientAnalyzerResult.zip") -> Path:
    """A Windows result, as its analyzer zips it: the report, the XML, and more beside."""
    path = folder / name
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("MDEClientAnalyzer.htm", "<html></html>")
        archive.writestr("SystemInfoLogs\\MDEClientAnalyzer.xml", WINDOWS_XML)
        archive.writestr("EventLogs\\System.evtx", b"\0" * 64)
    return path


def write_linux_zip(folder: Path, *, catalogue: bool = True, xml: str = LINUX_XML) -> Path:
    """A Linux (or, with MACOS_XML, macOS) result, with Linux's catalogue or without."""
    path = folder / ("mde_support.zip" if catalogue else "mde_support_binary.zip")
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("mde.xml", xml)
        archive.writestr("log.txt", "collected")
        if catalogue:
            archive.writestr("events.xml", LINUX_CATALOGUE)
    return path
