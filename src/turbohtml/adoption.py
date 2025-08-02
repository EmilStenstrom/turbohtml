"""
Adoption Agency Algorithm Implementation

This module implements the HTML5 Adoption Agency Algorithm for handling
mismatched formatting elements according to the WHATWG specification.

References:
- https://html.spec.whatwg.org/multipage/parsing.html#adoption-agency-algorithm
"""

from typing import List, Optional, Tuple, Dict, Any, Union
from dataclasses import dataclass

from .constants import FORMATTING_ELEMENTS, BLOCK_ELEMENTS

from turbohtml.node import Node
from turbohtml.tokenizer import HTMLToken
from turbohtml.constants import FORMATTING_ELEMENTS, BLOCK_ELEMENTS


@dataclass
class FormattingElementEntry:
    """Entry in the active formatting elements stack"""
    element: Node
    token: HTMLToken
    
    def matches(self, tag_name: str, attributes: Dict[str, str] = None) -> bool:
        """Check if this entry matches the given tag and attributes"""
        if self.element.tag_name != tag_name:
            return False
        
        if attributes is None:
            return True
            
        # Compare attributes (for Noah's Ark clause)
        return self.element.attributes == attributes


class ActiveFormattingElements:
    """
    Stack for tracking active formatting elements per HTML5 spec.
    
    Implements the active formatting elements list with:
    - Maximum size limit (no explicit limit in spec, but practical limit)
    - Noah's Ark clause (max 3 identical elements)
    - Markers for scope boundaries
    """
    
    def __init__(self, max_size: int = 12):
        self._stack: List[FormattingElementEntry] = []
        self._max_size = max_size
    
    def push(self, element: Node, token: HTMLToken) -> None:
        """Add a formatting element to the active list"""
        entry = FormattingElementEntry(element, token)
        
        # Apply Noah's Ark clause before adding
        self._apply_noahs_ark(entry)
        
        self._stack.append(entry)
        
        # Enforce maximum size (remove oldest if needed)
        if len(self._stack) > self._max_size:
            self._stack.pop(0)
    
    def find(self, tag_name: str, attributes: Dict[str, str] = None) -> Optional[FormattingElementEntry]:
        """Find a formatting element by tag name and optionally attributes"""
        # Search from most recent to oldest
        for entry in reversed(self._stack):
            if entry.matches(tag_name, attributes):
                return entry
        return None
    
    def find_element(self, element: Node) -> Optional[FormattingElementEntry]:
        """Find an entry by element instance"""
        for entry in self._stack:
            if entry.element is element:
                return entry
        return None
    
    def remove(self, element: Node) -> bool:
        """Remove a formatting element from the active list"""
        for i, entry in enumerate(self._stack):
            if entry.element is element:
                self._stack.pop(i)
                return True
        return False
    
    def remove_entry(self, entry: FormattingElementEntry) -> bool:
        """Remove a specific entry from the active list"""
        try:
            self._stack.remove(entry)
            return True
        except ValueError:
            return False
    
    def replace_entry(self, old_entry: FormattingElementEntry, new_element: Node, new_token: HTMLToken) -> None:
        """Replace an entry with a new element"""
        for i, entry in enumerate(self._stack):
            if entry is old_entry:
                self._stack[i] = FormattingElementEntry(new_element, new_token)
                return
        # If not found, just add it
        self.push(new_element, new_token)
    
    def clear_up_to_last_marker(self) -> None:
        """Clear elements up to the last marker (not implemented in basic version)"""
        # In full implementation, this would clear to last table/template boundary
        pass
    
    def get_elements_after(self, target_entry: FormattingElementEntry) -> List[FormattingElementEntry]:
        """Get all entries after the target entry"""
        try:
            index = self._stack.index(target_entry)
            return self._stack[index + 1:]
        except ValueError:
            return []
    
    def is_empty(self) -> bool:
        """Check if the stack is empty"""
        return len(self._stack) == 0
    
    def __len__(self) -> int:
        return len(self._stack)
    
    def __iter__(self):
        return iter(self._stack)
        
    def get_index(self, entry: FormattingElementEntry) -> int:
        """Get the index of an entry in the stack"""
        try:
            return self._stack.index(entry)
        except ValueError:
            return -1
            
    def insert_at_index(self, index: int, element: Node, token: HTMLToken) -> None:
        """Insert a new entry at the specified index"""
        entry = FormattingElementEntry(element, token)
        if 0 <= index <= len(self._stack):
            self._stack.insert(index, entry)
        else:
            self._stack.append(entry)
    
    def _apply_noahs_ark(self, new_entry: FormattingElementEntry) -> None:
        """
        Apply Noah's Ark clause: remove oldest identical element if we have 3+ 
        
        Per HTML5 spec: "If there are already three elements with the same tag name,
        namespace, and attributes on the list of active formatting elements, 
        then remove the earliest such element."
        """
        # Count identical elements
        identical_count = 0
        first_identical = None
        
        for entry in self._stack:
            if entry.matches(new_entry.element.tag_name, new_entry.element.attributes):
                identical_count += 1
                if first_identical is None:
                    first_identical = entry
        
        # If we already have 3, remove the first one
        if identical_count >= 3 and first_identical:
            self.remove_entry(first_identical)


class OpenElementsStack:
    """
    Enhanced stack of open elements with scope checking per HTML5 spec.
    
    Implements different scope types:
    - default scope
    - list item scope  
    - button scope
    - table scope
    - select scope
    """
    
    # Scope definitions per HTML5 spec
    DEFAULT_SCOPE_STOPPERS = {
        "applet", "caption", "html", "table", "td", "th", "marquee", "object", "template"
    }
    
    LIST_ITEM_SCOPE_STOPPERS = DEFAULT_SCOPE_STOPPERS | {"ol", "ul"}
    
    BUTTON_SCOPE_STOPPERS = DEFAULT_SCOPE_STOPPERS | {"button"}
    
    TABLE_SCOPE_STOPPERS = {"html", "table", "template"}
    
    SELECT_SCOPE_STOPPERS = {"optgroup", "option"}
    
    def __init__(self):
        self._stack: List[Node] = []
    
    def push(self, element: Node) -> None:
        """Push an element onto the stack"""
        self._stack.append(element)
    
    def pop(self) -> Optional[Node]:
        """Pop the top element from the stack"""
        if self._stack:
            return self._stack.pop()
        return None
    
    def current(self) -> Optional[Node]:
        """Get the current (top) element"""
        if self._stack:
            return self._stack[-1]
        return None
    
    def has_element_in_scope(self, tag_name: str, scope_type: str = "default") -> bool:
        """Check if an element with tag_name is in the specified scope"""
        stoppers = self._get_scope_stoppers(scope_type)
        
        # Search from top of stack down
        for element in reversed(self._stack):
            if element.tag_name == tag_name:
                return True
            if element.tag_name in stoppers:
                return False
        return False
    
    def find_furthest_block(self, formatting_element: Node) -> Optional[Node]:
        """Find the furthest block ancestor of formatting element"""
        # Find the formatting element in the stack first
        formatting_index = None
        for i, element in enumerate(self._stack):
            if element is formatting_element:
                formatting_index = i
                break
        
        if formatting_index is None:
            return None
        
        # Look for special category elements after the formatting element
        for i in range(formatting_index + 1, len(self._stack)):
            element = self._stack[i]
            if self._is_special_category(element):
                return element
        
        return None
    
    def pop_until(self, target_element: Node) -> List[Node]:
        """Pop elements until we reach the target element (inclusive)"""
        popped = []
        while self._stack:
            element = self.pop()
            popped.append(element)
            if element is target_element:
                break
        return popped
    
    def remove_element(self, element: Node) -> bool:
        """Remove a specific element from the stack"""
        try:
            self._stack.remove(element)
            return True
        except ValueError:
            return False
            
    def index_of(self, element: Node) -> int:
        """Get the index of an element in the stack (-1 if not found)"""
        try:
            return self._stack.index(element)
        except ValueError:
            return -1
            
    def contains(self, element: Node) -> bool:
        """Check if the element is in the stack"""
        return element in self._stack
            
    def replace_element(self, old_element: Node, new_element: Node) -> bool:
        """Replace an element in the stack"""
        try:
            index = self._stack.index(old_element)
            self._stack[index] = new_element
            return True
        except ValueError:
            return False
    
    def index_of(self, element: Node) -> int:
        """Get the index of an element in the stack"""
        try:
            return self._stack.index(element)
        except ValueError:
            return -1
    
    def __len__(self) -> int:
        return len(self._stack)
    
    def __iter__(self):
        return iter(self._stack)
    
    def is_empty(self) -> bool:
        """Check if the stack is empty"""
        return len(self._stack) == 0
    
    def _get_scope_stoppers(self, scope_type: str) -> set:
        """Get the scope stoppers for the specified scope type"""
        scope_map = {
            "default": self.DEFAULT_SCOPE_STOPPERS,
            "list_item": self.LIST_ITEM_SCOPE_STOPPERS,
            "button": self.BUTTON_SCOPE_STOPPERS,
            "table": self.TABLE_SCOPE_STOPPERS,
            "select": self.SELECT_SCOPE_STOPPERS,
        }
        return scope_map.get(scope_type, self.DEFAULT_SCOPE_STOPPERS)
        
    def _is_special_category(self, element: Node) -> bool:
        """Check if element is in the special category per HTML5 spec"""
        # Special category elements that can be "furthest blocks"
        special_elements = {
            "address", "applet", "area", "article", "aside", "base", "basefont",
            "bgsound", "blockquote", "body", "br", "button", "caption", "center",
            "col", "colgroup", "dd", "details", "dir", "div", "dl", "dt", "embed",
            "fieldset", "figcaption", "figure", "footer", "form", "frame", "frameset",
            "h1", "h2", "h3", "h4", "h5", "h6", "head", "header", "hgroup", "hr",
            "html", "iframe", "img", "input", "isindex", "li", "link", "listing",
            "main", "marquee", "menu", "meta", "nav", "noembed", "noframes",
            "noscript", "object", "ol", "p", "param", "plaintext", "pre", "script",
            "section", "select", "source", "style", "summary", "table", "tbody",
            "td", "template", "textarea", "tfoot", "th", "thead", "title", "tr",
            "track", "ul", "wbr", "xmp"
        }
        return element.tag_name in special_elements


class AdoptionAgencyAlgorithm:
    """
    Main implementation of the HTML5 Adoption Agency Algorithm.
    
    This handles the complex logic for adopting formatting elements when
    they are improperly nested or closed in the wrong order.
    """
    
    def __init__(self, parser):
        self.parser = parser
        self.debug_enabled = getattr(parser, 'env_debug', False)
    
    def _find_for_adoption(self, tag_name: str, context) -> Optional[FormattingElementEntry]:
        """Find the appropriate formatting element for adoption agency algorithm"""
        # For adoption agency, we need to find the formatting element that comes 
        # before any block elements in the stack of open elements
        
        # Get all formatting elements with this tag name
        candidates = []
        for entry in context.active_formatting_elements:
            if entry.element.tag_name == tag_name:
                candidates.append(entry)
        
        if not candidates:
            return None
            
        # Find the one that comes earliest in the open elements stack
        # (i.e., has the lowest index)
        best_candidate = None
        best_index = float('inf')
        
        for candidate in candidates:
            index = context.open_elements.index_of(candidate.element)
            if index >= 0 and index < best_index:
                best_index = index
                best_candidate = candidate
                
        return best_candidate

    def should_run_adoption(self, tag_name: str, context) -> bool:
        """
        Determine if the adoption agency algorithm should run for this tag.
        
        The algorithm runs when:
        1. It's an end tag for a formatting element
        2. The formatting element is in the active formatting elements list
        3. The formatting element is not in scope in the stack of open elements
        """
        if tag_name not in FORMATTING_ELEMENTS:
            return False
            
        # Check if element is in active formatting elements
        entry = context.active_formatting_elements.find(tag_name)
        if not entry:
            return False
            
        # Check if element is in scope in the stack of open elements
        if context.open_elements.has_element_in_scope(entry.element):
            return False
            
        return True
    
    def run_algorithm(self, tag_name: str, context) -> bool:
        """
        Run the HTML5 Adoption Agency Algorithm.
        
        Returns True if algorithm was run, False if not applicable.
        """
        if self.debug_enabled:
            print(f"    Adoption Agency: Checking if should run for {tag_name}")
            
        if not self.should_run_adoption(tag_name, context):
            if self.debug_enabled:
                print(f"    Adoption Agency: Not running for {tag_name}")
            return False
            
        if self.debug_enabled:
            print(f"    Adoption Agency: Running algorithm for {tag_name}")
        
        try:
            # Find the formatting element in active formatting elements
            # For adoption agency, we need the FIRST (oldest) occurrence, not the last
            formatting_entry = self._find_for_adoption(tag_name, context)
            if not formatting_entry:
                if self.debug_enabled:
                    print(f"    Adoption Agency: No formatting element found for {tag_name}")
                return False
            
            formatting_element = formatting_entry.element
            if self.debug_enabled:
                print(f"    Adoption Agency: Found formatting element: {formatting_element}")
            
            # Check if formatting element is in the stack of open elements
            if not context.open_elements.contains(formatting_element):
                if self.debug_enabled:
                    print(f"    Adoption Agency: Formatting element not in open elements, removing from active formatting")
                context.active_formatting_elements.remove(formatting_element)
                return False
            
            # Ensure current_parent is never None before continuing
            if context.current_parent is None:
                if self.debug_enabled:
                    print(f"    Adoption Agency: WARNING - current_parent is None, setting to root")
                context.current_parent = context.root
            
            # Find the furthest block (first block element after formatting element)
            furthest_block = self._find_furthest_block(formatting_element, context)
            if self.debug_enabled:
                print(f"    Adoption Agency: Furthest block: {furthest_block}")
                print(f"    Adoption Agency: Open elements stack: {[elem.tag_name for elem in context.open_elements._stack]}")
                formatting_index = context.open_elements.index_of(formatting_element)
                print(f"    Adoption Agency: Formatting element {formatting_element.tag_name} at index {formatting_index}")
                if formatting_index >= 0:
                    print(f"    Adoption Agency: Elements after formatting element: {[elem.tag_name for elem in context.open_elements._stack[formatting_index + 1:]]}")
            
            if furthest_block is None:
                # No furthest block - handle this case
                if self.debug_enabled:
                    print(f"    Adoption Agency: No furthest block, handling simple case")
                return self._handle_no_furthest_block(formatting_element, formatting_entry, context)
            else:
                # Run complex algorithm
                if self.debug_enabled:
                    print(f"    Adoption Agency: Running complex algorithm")
                return self._run_complex_adoption(formatting_entry, furthest_block, context)
                
        except Exception as e:
            if self.debug_enabled:
                print(f"    Adoption Agency: Error during algorithm: {e}")
                import traceback
                traceback.print_exc()
            return False
        
    def _find_furthest_block(self, formatting_element: Node, context) -> Optional[Node]:
        """Find the furthest block element after the formatting element in the stack"""
        formatting_index = context.open_elements.index_of(formatting_element)
        if formatting_index == -1:
            return None
            
        # Look for block elements after the formatting element
        for i in range(formatting_index + 1, len(context.open_elements._stack)):
            element = context.open_elements._stack[i]
            if element.tag_name in BLOCK_ELEMENTS:
                return element
                
        return None

    def _handle_no_furthest_block(self, formatting_element: Node, formatting_entry: FormattingElementEntry, context) -> bool:
        """Handle adoption agency when there's no furthest block"""
        
        # Find all formatting elements that are descendants of the closing element
        elements_to_reconstruct = []
        
        # Look through the open elements stack to find formatting elements after our target
        formatting_index = context.open_elements.index_of(formatting_element)
        
        for i in range(formatting_index + 1, len(context.open_elements._stack)):
            element = context.open_elements._stack[i]
            if element.tag_name in FORMATTING_ELEMENTS:
                entry = context.active_formatting_elements.find_element(element)
                if entry:
                    elements_to_reconstruct.append((element, entry))
        
        # Step 1: Close everything up to the formatting element
        context.open_elements.pop_until(formatting_element)
        context.active_formatting_elements.remove(formatting_element)
        
        # Step 2: Update current_parent to the parent of the formatting element
        if formatting_element.parent:
            context.current_parent = formatting_element.parent
        elif not context.open_elements.is_empty():
            # Fallback to top of open elements stack
            context.current_parent = context.open_elements._stack[-1]
        else:
            # Ultimate fallback - find body or html
            body = context.root.find_child("body")
            if body:
                context.current_parent = body
            else:
                context.current_parent = context.root
        
        # Step 3: Reconstruct any formatting elements that were inside the closed element
        for element, entry in elements_to_reconstruct:
            # Create a new formatting element
            new_element = Node(element.tag_name, element.attributes.copy())
            
            # Add it as a child of the current parent (ensure current_parent is not None)
            if context.current_parent:
                context.current_parent.append_child(new_element)
            
                # Add to stacks
                context.open_elements.push(new_element)
                context.active_formatting_elements.push(new_element, entry.token)
                
                # Update current parent to the new element
                context.current_parent = new_element
        
        return True
    
    def _run_complex_adoption(self, formatting_entry: FormattingElementEntry, furthest_block: Node, context) -> bool:
        """Run the complex part of the adoption agency algorithm"""
        formatting_element = formatting_entry.element
        
        # Step 1: The formatting element keeps its existing content (don't remove children)
        # This preserves text/elements that were added before the furthest block
        
        # Remember where parsing was when adoption agency started
        original_current_parent = context.current_parent
        
        # Step 2: Find all block elements that need reconstruction
        formatting_index = context.open_elements.index_of(formatting_element)
        
        # Find all blocks after the formatting element
        blocks_to_reconstruct = []
        for i in range(formatting_index + 1, len(context.open_elements._stack)):
            element = context.open_elements._stack[i]
            if element.tag_name in BLOCK_ELEMENTS:
                blocks_to_reconstruct.append(element)
        
        # Step 3: For each block, reconstruct the formatting element
        for block_element in blocks_to_reconstruct:
            # Create a new formatting element for this block
            new_formatting_element = Node(formatting_element.tag_name, formatting_element.attributes.copy())
            
            # Move appropriate content that should be inside the formatting element
            children_to_move = []
            for child in block_element.children:
                if child.tag_name == "#text":
                    children_to_move.append(child)
                elif child.tag_name in FORMATTING_ELEMENTS:
                    children_to_move.append(child)
                else:
                    # Stop at first block element
                    break
            
            # Move the identified children to the new formatting element
            for child in children_to_move:
                block_element.remove_child(child)
                new_formatting_element.append_child(child)
            
            # Always insert the new formatting element, even if it's empty
            # This matches HTML5 spec behavior for adoption agency
            block_element.children.insert(0, new_formatting_element)
            new_formatting_element.parent = block_element
            
            # Update sibling links
            if len(block_element.children) > 1:
                new_formatting_element.next_sibling = block_element.children[1]
                block_element.children[1].previous_sibling = new_formatting_element
            new_formatting_element.previous_sibling = None
            
            # Add to active formatting elements
            context.active_formatting_elements.push(new_formatting_element, formatting_entry.token)
        
        # Step 4: Remove the old formatting element from both stacks
        context.open_elements.remove_element(formatting_element)
        context.active_formatting_elements.remove(formatting_element)
        
        # Step 5: Set current parent back to where parsing was when adoption agency started
        # This ensures subsequent content goes to the right place
        context.current_parent = original_current_parent
        
        # Double-check that current_parent is never None
        if context.current_parent is None:
            context.current_parent = context.root
        
        return True
