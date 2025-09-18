#!/usr/bin/env python3
"""
JWZ Threading Algorithm Implementation

Based on Jamie Zawinski's algorithm described at:
https://www.jwz.org/doc/threading.html

This implements the full JWZ threading algorithm for email messages.
"""

import re
from typing import List, Dict, Optional, Set, Callable
from dataclasses import dataclass


@dataclass
class Message:
    """Represents an email message for threading"""
    message_id: str
    subject: str
    references: List[str]
    date: object = None  # Can be any comparable object (datetime, timestamp, etc.)

    def __post_init__(self):
        # Ensure references is a list
        if self.references is None:
            self.references = []


class Container:
    """Container object for threading algorithm"""

    def __init__(self, message: Optional[Message] = None):
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


def _prune_empty_containers(containers: List[Container]) -> List[Container]:
    """Prune empty containers from the thread tree"""
    result = []

    for container in containers:
        # First, recursively prune children
        container.children = _prune_empty_containers(container.children)

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


def _default_sort(containers: List[Container]):
    """Default sort function - sort by date"""
    containers.sort(key=lambda c: c.message.date if c.message and c.message.date else 0)


def _sort_all_children(containers: List[Container], sort_func: Callable):
    """Recursively sort all children in container tree"""
    sort_func(containers)
    for container in containers:
        if container.children:
            _sort_all_children(container.children, sort_func)


def extract_message_ids(header_value: str) -> List[str]:
    """Extract message IDs from References or In-Reply-To header"""
    if not header_value:
        return []

    # Find all <message-id> patterns
    message_ids = re.findall(r'<([^>]+)>', header_value)
    return message_ids


def thread_messages(messages, sort_func: Optional[Callable] = None) -> List[Container]:
    """
    Thread a list of messages using the JWZ algorithm

    Args:
        messages: List of EmailMessage objects to thread
        sort_func: Optional function to sort containers. Should accept a list of containers.
                  If None, containers are sorted by date.

    Returns:
        List of root Container objects representing the threaded structure
    """

    # Step 1: Build the id_table and create containers
    id_table: Dict[str, Container] = {}

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

    # Step 2: Find root set
    root_set = []
    for container in id_table.values():
        if container.parent is None:
            root_set.append(container)

    # Step 3: Prune empty containers
    root_set = _prune_empty_containers(root_set)

    # Step 4: Group by subject
    subject_table: Dict[str, Container] = {}

    # Build subject table
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

    # Group containers with same subject
    new_root_set = []
    processed: Set[Container] = set()

    for container in root_set:
        if container in processed:
            continue

        subject = normalize_subject(container.get_subject())
        if not subject or subject not in subject_table:
            new_root_set.append(container)
            processed.add(container)
            continue

        table_container = subject_table[subject]
        if table_container == container:
            new_root_set.append(container)
            processed.add(container)
            continue

        # Group the containers
        if table_container in processed:
            # Table container already processed, add this as child
            if not container.get_subject().lower().startswith('re:'):
                # This is not a reply, make it parent
                dummy = Container()
                dummy.add_child(table_container)
                dummy.add_child(container)
                # Find and replace table_container in new_root_set
                if table_container in new_root_set:
                    idx = new_root_set.index(table_container)
                    new_root_set[idx] = dummy
                else:
                    new_root_set.append(dummy)
            else:
                # This is a reply, add as child
                if table_container in new_root_set:
                    table_container.add_child(container)
        else:
            # Neither processed yet
            if (table_container.is_dummy() and not container.is_dummy()):
                table_container.add_child(container)
                new_root_set.append(table_container)
            elif (not table_container.is_dummy() and container.is_dummy()):
                container.add_child(table_container)
                new_root_set.append(container)
            elif (not table_container.get_subject().lower().startswith('re:') and
                  container.get_subject().lower().startswith('re:')):
                table_container.add_child(container)
                new_root_set.append(table_container)
            elif (table_container.get_subject().lower().startswith('re:') and
                  not container.get_subject().lower().startswith('re:')):
                container.add_child(table_container)
                new_root_set.append(container)
            else:
                # Both are replies or both are not - make siblings
                dummy = Container()
                dummy.add_child(table_container)
                dummy.add_child(container)
                new_root_set.append(dummy)

            processed.add(table_container)

        processed.add(container)

    # Step 5: Sort siblings
    if sort_func is None:
        # Default sort by date
        sort_func = _default_sort

    _sort_all_children(new_root_set, sort_func)
    sort_func(new_root_set)

    return new_root_set


def print_thread_tree(containers: List[Container], indent: int = 0):
    """Print the thread tree for debugging"""
    for container in containers:
        prefix = "  " * indent
        if container.message:
            print(f"{prefix}{container.message.subject} ({container.message.message_id})")
        else:
            print(f"{prefix}[dummy container]")

        if container.children:
            print_thread_tree(container.children, indent + 1)



def thread(messages, sort_func=None):
    """
    Thread messages using JWZ algorithm

    Args:
        messages: List of EmailMessage objects
        sort_func: Function to sort containers

    Returns:
        List of root containers with EmailMessage objects
    """
    return thread_messages(messages, sort_func)


if __name__ == "__main__":
    # Test with some sample messages
    test_messages = [
        Message("1@example.com", "Hello", []),
        Message("2@example.com", "Re: Hello", ["1@example.com"]),
        Message("3@example.com", "Re: Hello", ["1@example.com", "2@example.com"]),
        Message("4@example.com", "Another topic", []),
        Message("5@example.com", "Re: Another topic", ["4@example.com"]),
    ]

    threaded = thread_messages(test_messages)
    print("Threaded messages:")
    print_thread_tree(threaded)