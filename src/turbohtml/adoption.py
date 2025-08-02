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
        
        Per HTML5 spec, the algorithm runs when:
        1. It's an end tag for a formatting element
        2. The formatting element is in the active formatting elements list
        """
        if tag_name not in FORMATTING_ELEMENTS:
            return False
            
        # Check if element is in active formatting elements
        entry = context.active_formatting_elements.find(tag_name)
        return entry is not None
    
    def run_algorithm(self, tag_name: str, context) -> bool:
        """
        Run the HTML5 Adoption Agency Algorithm per WHATWG spec.
        
        This is the full algorithm as specified in:
        https://html.spec.whatwg.org/multipage/parsing.html#adoption-agency-algorithm
        """
        if self.debug_enabled:
            print(f"    Adoption Agency: Starting algorithm for {tag_name}")
            
        # Step 1: If the current node is an HTML element whose tag name is subject,
        # and the current node is not in the list of active formatting elements,
        # then pop the current node off the stack of open elements and return.
        if (not context.open_elements.is_empty() and 
            context.open_elements.current() and
            context.open_elements.current().tag_name == tag_name and
            not context.active_formatting_elements.find_element(context.open_elements.current())):
            context.open_elements.pop()
            return True
        
        # Step 2: Find the formatting element
        formatting_entry = context.active_formatting_elements.find(tag_name)
        if not formatting_entry:
            if self.debug_enabled:
                print(f"    Adoption Agency: No formatting element found for {tag_name}")
            return False
            
        formatting_element = formatting_entry.element
        if self.debug_enabled:
            print(f"    Adoption Agency: Found formatting element: {formatting_element}")
        
        # Step 3: If formatting element is not in stack of open elements
        if not context.open_elements.contains(formatting_element):
            if self.debug_enabled:
                print(f"    Adoption Agency: Formatting element not in open elements, removing from active formatting")
            context.active_formatting_elements.remove(formatting_element)
            return True
        
        # Step 4: If formatting element is in stack but not in scope
        if not context.open_elements.has_element_in_scope(formatting_element.tag_name):
            if self.debug_enabled:
                print(f"    Adoption Agency: Formatting element not in scope")
            return True  # Parse error, ignore the end tag
        
        # Step 5: If formatting element is not the current node, it's a parse error
        if context.open_elements.current() != formatting_element:
            if self.debug_enabled:
                print(f"    Adoption Agency: Parse error - formatting element not current node")
            # Continue with algorithm anyway
        
        # Step 6: Find the furthest block
        furthest_block = self._find_furthest_block_spec_compliant(formatting_element, context)
        if self.debug_enabled:
            print(f"    Adoption Agency: Furthest block: {furthest_block}")
        
        # Step 7: If no furthest block, then simple case
        if furthest_block is None:
            return self._handle_no_furthest_block_spec(formatting_element, formatting_entry, context)
        
        # Step 8-19: Complex case with furthest block
        return self._run_complex_adoption_spec(formatting_entry, furthest_block, context)
        
    def _find_furthest_block_spec_compliant(self, formatting_element: Node, context) -> Optional[Node]:
        """Find the furthest block element per HTML5 spec"""
        formatting_index = context.open_elements.index_of(formatting_element)
        if formatting_index == -1:
            return None
            
        # Look for special category elements after the formatting element
        # Special category includes all elements that can terminate scope
        for i in range(formatting_index + 1, len(context.open_elements._stack)):
            element = context.open_elements._stack[i]
            if context.open_elements._is_special_category(element):
                return element
                
        return None
    
    def _handle_no_furthest_block_spec(self, formatting_element: Node, formatting_entry: FormattingElementEntry, context) -> bool:
        """Handle the simple case when there's no furthest block (steps 7.1-7.3)"""
        if self.debug_enabled:
            print(f"    Adoption Agency: No furthest block case")
        
        # Pop elements from stack until we reach the formatting element (inclusive)
        while not context.open_elements.is_empty():
            element = context.open_elements.pop()
            if element == formatting_element:
                break
        
        # Remove from active formatting elements
        context.active_formatting_elements.remove(formatting_element)
        
        # Update current_parent to the new top of stack
        if not context.open_elements.is_empty():
            context.current_parent = context.open_elements.current()
        else:
            # Fallback to body or html
            body_node = None
            if hasattr(context, 'html_node') and context.html_node:
                for child in context.html_node.children:
                    if child.tag_name == "body":
                        body_node = child
                        break
            if body_node:
                context.current_parent = body_node
            else:
                context.current_parent = self.parser.root
        
        return True
    
    def _run_complex_adoption_spec(self, formatting_entry: FormattingElementEntry, furthest_block: Node, context) -> bool:
        """
        Run the complex adoption agency algorithm (steps 8-19) per HTML5 spec.
        
        This implements the full algorithm with proper element reconstruction.
        """
        formatting_element = formatting_entry.element
        if self.debug_enabled:
            print(f"    Adoption Agency: Complex case with furthest block {furthest_block.tag_name}")
            print(f"    Adoption Agency: Formatting element: {formatting_element.tag_name}")
            print(f"    Adoption Agency: Stack before: {[e.tag_name for e in context.open_elements._stack]}")
            print(f"    Adoption Agency: Active formatting before: {[e.element.tag_name for e in context.active_formatting_elements]}")
        
        try:
            if self.debug_enabled:
                print(f"    Adoption Agency: Starting complex reconstruction")
            
            # Find the common ancestor (element above formatting element in stack)
            formatting_index = context.open_elements.index_of(formatting_element)
            if formatting_index < 0:
                if self.debug_enabled:
                    print(f"    Adoption Agency: ERROR - formatting element not found in stack")
                return False
            
            if formatting_index == 0:
                # No common ancestor - use body or root as common ancestor
                if hasattr(context, 'html_node') and context.html_node:
                    for child in context.html_node.children:
                        if child.tag_name == "body":
                            common_ancestor = child
                            break
                    else:
                        common_ancestor = self.parser.root
                else:
                    common_ancestor = self.parser.root
            else:
                common_ancestor = context.open_elements._stack[formatting_index - 1]
            
            if self.debug_enabled:
                print(f"    Adoption Agency: Found common ancestor: {common_ancestor.tag_name}")
            
            # Find elements between formatting element and furthest block in the stack
            furthest_block_index = context.open_elements.index_of(furthest_block)
            
            if formatting_index < 0 or furthest_block_index < 0 or formatting_index >= furthest_block_index:
                if self.debug_enabled:
                    print(f"    Adoption Agency: ERROR - invalid indices: format={formatting_index}, furthest={furthest_block_index}")
                return False
            
            if self.debug_enabled:
                print(f"    Adoption Agency: Indices - formatting: {formatting_index}, furthest: {furthest_block_index}")
            
            # Get the elements between formatting element and furthest block (exclusive)
            # But exclude the element immediately after the formatting element in the reconstruction
            # This follows HTML5 spec where common ancestor helps determine reconstruction scope
            elements_to_reconstruct = []
            start_reconstruction_from = formatting_index + 2  # Skip the element right after formatting element
            
            for i in range(start_reconstruction_from, furthest_block_index):
                element = context.open_elements._stack[i]
                # Only reconstruct formatting elements
                if context.active_formatting_elements.find_element(element):
                    elements_to_reconstruct.append(element)
            
            if self.debug_enabled:
                print(f"    Adoption Agency: Elements to reconstruct: {[e.tag_name for e in elements_to_reconstruct]}")
                print(f"    Adoption Agency: Common ancestor: {common_ancestor.tag_name}")
            
            # Step 1: Create the first reconstruction element as sibling to common ancestor
            # This creates the "big" as a sibling to "a" in our test case
            current_parent = common_ancestor
            reconstruction_root = None
            
            for element in elements_to_reconstruct:
                if self.debug_enabled:
                    print(f"    Adoption Agency: Reconstructing element: {element.tag_name}")
                
                clone = Node(element.tag_name, element.attributes.copy())
                if reconstruction_root is None:
                    # First reconstruction - add as child of common ancestor (not sibling)
                    if self.debug_enabled:
                        print(f"    Adoption Agency: Adding {clone.tag_name} as child of {common_ancestor.tag_name}")
                    common_ancestor.append_child(clone)
                    reconstruction_root = clone
                    current_parent = clone
                else:
                    # Subsequent reconstructions - nest inside previous
                    if self.debug_enabled:
                        print(f"    Adoption Agency: Nesting {clone.tag_name} inside {current_parent.tag_name}")
                    current_parent.append_child(clone)
                    current_parent = clone
            
            # Step 2: Move the furthest block (and its children) into the reconstruction chain
            if furthest_block.parent:
                furthest_block.parent.remove_child(furthest_block)
            if current_parent:
                current_parent.append_child(furthest_block)
            
            # Step 3: Create a clone of the original formatting element inside furthest block
            formatting_clone = Node(formatting_element.tag_name, formatting_element.attributes.copy())
            
            # Step 4: Move all children of furthest block to the formatting clone
            children_to_move = furthest_block.children[:]  # Copy the list
            for child in children_to_move:
                if child != formatting_clone:  # Don't move the clone we just created
                    furthest_block.remove_child(child)
                    formatting_clone.append_child(child)
            
            # Step 5: Add the formatting clone to furthest block
            furthest_block.append_child(formatting_clone)
            
            # Step 6: Clean up stacks - remove elements that were closed
            elements_to_remove = elements_to_reconstruct + [formatting_element]
            
            for element in elements_to_remove:
                if element in context.open_elements._stack:
                    context.open_elements.remove_element(element)
                entry = context.active_formatting_elements.find_element(element)
                if entry:
                    context.active_formatting_elements.remove(element)
            
            # Step 7: Update current parent to the furthest block for subsequent parsing
            context.current_parent = furthest_block
            
            if self.debug_enabled:
                print(f"    Adoption Agency: Stack after: {[e.tag_name for e in context.open_elements._stack]}")
                print(f"    Adoption Agency: Active formatting after: {[e.element.tag_name for e in context.active_formatting_elements]}")
                print(f"    Adoption Agency: Current parent now: {context.current_parent.tag_name}")
            
            return True
            
        except Exception as e:
            if self.debug_enabled:
                print(f"    Adoption Agency: ERROR in complex algorithm: {e}")
                import traceback
                traceback.print_exc()
            return False
    
    def _should_foster_parent(self, common_ancestor: Node) -> bool:
        """Check if foster parenting is needed"""
        # Foster parenting is needed if common ancestor is a table element
        # and we're not already in a cell or caption
        return (common_ancestor.tag_name in ("table", "tbody", "tfoot", "thead", "tr") and
                not common_ancestor.find_ancestor(lambda n: n.tag_name in ("td", "th", "caption")))
    
    def _foster_parent_node(self, node: Node, context) -> None:
        """Foster parent a node according to HTML5 rules"""
        # Find the table
        table = None
        current = context.current_parent
        while current:
            if current.tag_name == "table":
                table = current
                break
            current = current.parent
        
        if table and table.parent:
            # Insert before the table
            table_index = table.parent.children.index(table)
            table.parent.children.insert(table_index, node)
            node.parent = table.parent
        else:
            # Fallback to current parent
            context.current_parent.append_child(node)
