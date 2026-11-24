"""Filtros subtree NETCONF para el BRAS."""

from __future__ import annotations

import xml.etree.ElementTree as ET

BRAS_NS = "urn:huawei:yang:huawei-bras-user-manage"
QOS_NS = "urn:huawei:yang:huawei-qos"


def _tag(name: str, namespace: str) -> str:
    return f"{{{namespace}}}{name}"


def _serialize(root: ET.Element) -> str:
    return ET.tostring(root, encoding="unicode")


def access_user_filter(username: str) -> str:
    root = ET.Element(_tag("bras-user-manage", BRAS_NS))
    tables = ET.SubElement(root, _tag("access-tables", BRAS_NS))
    table = ET.SubElement(tables, _tag("access-table", BRAS_NS))
    basic = ET.SubElement(table, _tag("access-user-basic-info", BRAS_NS))
    ET.SubElement(basic, _tag("access-user-name", BRAS_NS)).text = username
    for name in ("access-ipaddress", "access-mac-address", "access-start-time"):
        ET.SubElement(basic, _tag(name, BRAS_NS))
    return _serialize(root)


def offline_records_filter(username: str, count: int) -> str:
    root = ET.Element(_tag("bras-user-manage", BRAS_NS))
    records = ET.SubElement(root, _tag("online-fail-or-offline-records", BRAS_NS))
    record = ET.SubElement(records, _tag("online-fail-or-offline-record", BRAS_NS))
    ET.SubElement(record, _tag("record-type", BRAS_NS)).text = "offline-record"
    ET.SubElement(record, _tag("user-name", BRAS_NS)).text = username
    for name in (
        "mac-address",
        "ipv4-address",
        "login-time",
        "offline-time",
        "online-fail-or-offline-reason",
    ):
        ET.SubElement(record, _tag(name, BRAS_NS))
    ET.SubElement(record, _tag("view-count", BRAS_NS)).text = str(count)
    return _serialize(root)


def qos_filter(access_index: int) -> str:
    root = ET.Element(_tag("qos", QOS_NS))
    global_query = ET.SubElement(root, _tag("global-query", QOS_NS))
    users = ET.SubElement(global_query, _tag("user-informations", QOS_NS))
    user = ET.SubElement(users, _tag("user-information", QOS_NS))
    ET.SubElement(user, _tag("id", QOS_NS)).text = str(access_index)
    ET.SubElement(user, _tag("direction", QOS_NS))
    stats = ET.SubElement(user, _tag("user-queue-statisticss", QOS_NS))
    stat = ET.SubElement(stats, _tag("user-queue-statistics", QOS_NS))
    ET.SubElement(stat, _tag("service-class", QOS_NS)).text = "total"
    ET.SubElement(stat, _tag("pass-bytes", QOS_NS))
    return _serialize(root)
