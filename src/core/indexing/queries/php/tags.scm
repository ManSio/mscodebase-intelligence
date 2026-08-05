; PHP tags query

; Functions
(function_definition
  name: (name) @name
  (#set! "kind" "function")
) @definition.function

; Methods
(method_declaration
  name: (name) @name
  (#set! "kind" "method")
) @definition.method

; Classes
(class_declaration
  name: (name) @name
  (#set! "kind" "class")
) @definition.class

; Interfaces
(interface_declaration
  name: (name) @name
  (#set! "kind" "interface")
) @definition.interface

; Traits
(trait_declaration
  name: (name) @name
  (#set! "kind" "trait")
) @definition.interface

; Attributes (PHP 8)
(attribute
  (name) @name
  (#set! "kind" "attribute")
) @definition.decorator

; Calls
(function_call_expression
  function: (name) @name
) @reference.call

(method_call_expression
  name: (name) @name
) @reference.call

; Imports
(use_clause
  (use_declaration
    (name) @module
  )
) @definition.import

; Variables
(variable_name
  (name) @name
) @definition.variable

; Constants
(const_declaration
  (const_element
    (name) @name
  )
) @definition.variable