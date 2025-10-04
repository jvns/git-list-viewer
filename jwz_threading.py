#!/usr/bin/env python3
"""
Based on Jamie Zawinski's algorithm described at:
https://www.jwz.org/doc/threading.html
"""

import re
from typing import List, Dict, Optional, Set, Callable
from dataclasses import dataclass

class Container:
    """Container object for threading algorithm"""

    def __init__(self, message = None):
        self.message = message
        self.parent: Optional['Container'] = None
        self.children: List['Container'] = []

    def add_child(self, child: 'Container'):
        """Add a child container"""
        if child.parent:
            child.parent.remove_child(child)

        child.parent = self
        self.children.append(child)

    def remove_child(self, child: 'Container'):
        """Remove a child container"""
        if child in self.children:
            self.children.remove(child)
            child.parent = None

    def has_descendant(self, container: 'Container') -> bool:
        """Check if container is a descendant of this container"""
        for child in self.children:
            if child == container or child.has_descendant(container):
                return True
        return False

    def is_dummy(self) -> bool:
        """Check if this is an empty container (no message)"""
        return self.message is None

    def get_subject(self) -> str:
        """Get the subject for this container"""
        if self.message:
            return self.message.subject
        elif self.children:
            return self.children[0].get_subject()
        return ""


def normalize_subject(subject: str) -> str:
    """Strip Re: prefixes from subject"""
    if not subject:
        return ""

    # Remove Re: prefixes (case insensitive, with optional numbers)
    subject = re.sub(r'^(re|RE)(\[\d+\])?:\s*', '', subject)
    subject = re.sub(r'^(re|RE):\s*', '', subject)  # Handle multiple Re:'s

    return subject.strip()


def prune_empty_containers(containers: List[Container]) -> List[Container]:
    """Prune empty containers from the thread tree"""
    result = []

    for container in containers:
        # First, recursively prune children
        container.children = prune_empty_containers(container.children)

        if container.is_dummy() and not container.children:
            # Empty container with no children - discard it
            continue
        elif container.is_dummy() and container.children:
            # Empty container with children
            if container.parent is None:
                # At root level - promote children if there's only one
                if len(container.children) == 1:
                    child = container.children[0]
                    child.parent = None
                    result.append(child)
                else:
                    # Keep the dummy container to group children
                    result.append(container)
            else:
                # Not at root level - promote all children
                for child in container.children:
                    child.parent = container.parent
                    result.append(child)
        else:
            # Non-empty container - keep it
            result.append(container)

    return result


def build_subject_table(root_set: List[Container]) -> Dict[str, Container]:
    """Build subject table for grouping containers by normalized subject"""
    subject_table: Dict[str, Container] = {}

    for container in root_set:
        subject = normalize_subject(container.get_subject())
        if not subject:
            continue

        if subject not in subject_table:
            subject_table[subject] = container
        else:
            existing = subject_table[subject]

            # Prefer non-dummy containers
            if existing.is_dummy() and not container.is_dummy():
                subject_table[subject] = container
            # Prefer non-Re subjects
            elif (existing.get_subject().lower().startswith('re:') and
                  not container.get_subject().lower().startswith('re:')):
                subject_table[subject] = container

    return subject_table


def sort_all_children(containers):
    """Recursively sort all children in container tree by date"""
    containers.sort(key=lambda c: c.message.date if c.message and c.message.date else 0)
    for container in containers:
        if container.children:
            sort_all_children(container.children)


def build_containers_from_messages(messages):
    """Build initial container tree from messages and their references"""
    id_table = {}

    for message in messages:
        # Find or create container for this message
        if message.message_id in id_table:
            container = id_table[message.message_id]
            container.message = message
        else:
            container = Container(message)
            id_table[message.message_id] = container

        # Process references - deduplicate to avoid loops
        prev_container = None
        unique_refs = []
        seen = set()
        for ref_id in message.references:
            if ref_id not in seen:
                unique_refs.append(ref_id)
                seen.add(ref_id)

        for ref_id in unique_refs:
            # Find or create container for this reference
            if ref_id not in id_table:
                id_table[ref_id] = Container()

            ref_container = id_table[ref_id]

            # Link containers if not already linked and won't create loop
            if prev_container and not ref_container.parent and not ref_container.has_descendant(prev_container):
                prev_container.add_child(ref_container)

            prev_container = ref_container

        # Set parent to last reference if exists and won't create loop
        if prev_container and not container.has_descendant(prev_container):
            prev_container.add_child(container)

    return id_table


def group_by_subject(root_set):
    """Group containers with the same subject together"""
    subject_table = build_subject_table(root_set)
    grouped_set = []
    processed = set()

    for container in root_set:
        if container in processed:
            continue

        subject = normalize_subject(container.get_subject())
        if not subject or subject not in subject_table:
            grouped_set.append(container)
            processed.add(container)
            continue

        table_container = subject_table[subject]
        if table_container == container:
            grouped_set.append(container)
            processed.add(container)
            continue

        # Group the containers based on subject threading rules
        merge_subject_containers(container, table_container, grouped_set, processed)
        processed.add(container)

    return grouped_set


def merge_subject_containers(container, table_container, grouped_set, processed):
    """Merge two containers with the same subject according to threading rules"""
    if table_container in processed:
        # Table container already processed
        if not container.get_subject().lower().startswith('re:'):
            # This is not a reply, make it parent
            dummy = Container()
            dummy.add_child(table_container)
            dummy.add_child(container)
            # Replace table_container in grouped_set
            if table_container in grouped_set:
                idx = grouped_set.index(table_container)
                grouped_set[idx] = dummy
            else:
                grouped_set.append(dummy)
        else:
            # This is a reply, add as child
            if table_container in grouped_set:
                table_container.add_child(container)
    else:
        # Neither processed yet - decide parent/child relationship
        if (table_container.is_dummy() and not container.is_dummy()):
            table_container.add_child(container)
            grouped_set.append(table_container)
        elif (not table_container.is_dummy() and container.is_dummy()):
            container.add_child(table_container)
            grouped_set.append(container)
        elif (not table_container.get_subject().lower().startswith('re:') and
              container.get_subject().lower().startswith('re:')):
            table_container.add_child(container)
            grouped_set.append(table_container)
        elif (table_container.get_subject().lower().startswith('re:') and
              not container.get_subject().lower().startswith('re:')):
            container.add_child(table_container)
            grouped_set.append(container)
        else:
            # Both are replies or both are not - make siblings
            dummy = Container()
            dummy.add_child(table_container)
            dummy.add_child(container)
            grouped_set.append(dummy)

        processed.add(table_container)


def _normalize_subject(subject):
    return re.sub(r"^(Re|Fwd|Fw):\s*", "", subject, flags=re.IGNORECASE).strip()


def _display_subject(msg, parent_subject, level):
    display_subject = msg.subject
    if parent_subject and level > 0:
        parent_normalized = _normalize_subject(parent_subject)
        current_normalized = _normalize_subject(msg.subject)
        if parent_normalized and parent_normalized in current_normalized:
            display_subject = ""
    return display_subject

def _flatten(containers, level=0, parent_subject=None):
    for container in containers:
        if hasattr(container, 'message'):
            msg = container.message
            msg.display_subject = _display_subject(msg, parent_subject, level)
            msg.level = level
            yield msg

            # Process children, passing current subject as parent
            if hasattr(container, 'children') and container.children:
                yield from _flatten(container.children, level + 1, msg.subject)
        else:
            # Dummy container - process children with same parent subject
            if hasattr(container, 'children') and container.children:
                yield from _flatten(container.children, level, parent_subject)

def thread(messages):
    # Step 1: Build the container tree from messages and references
    id_table = build_containers_from_messages(messages)

    # Step 2: Find root containers (those with no parent)
    root_set = [container for container in id_table.values() if container.parent is None]

    # Step 3: Prune empty containers
    root_set = prune_empty_containers(root_set)

    # Step 4: Group containers by subject
    root_set = group_by_subject(root_set)

    # Step 5: Sort all containers by date
    sort_all_children(root_set)

    # Step 6: Flatten & normalize subjects
    messages = list(_flatten(root_set))

    return messages
