; Python tags query
; Extends the standard tree-sitter queries/tags.scm

; Functions and methods
(function_definition
  name: (identifier) @name
  (#set! "kind" "function")
) @definition.function

(class_definition
  name: (identifier) @name
  (#set! "kind" "class")
) @definition.class

; Decorated definitions
(decorated_definition
  (decorator)* @_deco
  [
    (function_definition name: (identifier) @name)
    (class_definition name: (identifier) @name)
  ]
  (#set! "kind" "function")
) @definition.function

; Async functions
(async_function_definition
  name: (identifier) @name
  (#set! "kind" "function")
) @definition.function

; Lambda - not a definition, but a reference
(lambda
  parameters: (parameters) @params
) @reference.function

; Call expressions
(call_expression
  function: (_) @name
  (#not-match? @name "^[a-z_][a-z0-9_]*$")
) @reference.call

(call_expression
  function: (attribute
    object: (_)
    attribute: (identifier) @name
  )
) @reference.call

; Imports
(import_statement
  name: (dotted_name) @module
) @definition.import

(import_from_statement
  module_name: (dotted_name) @module
) @definition.import

; Variables and assignments
(assignment
  left: (identifier) @name
) @definition.variable

(assignment
  left: (attribute
    object: (_)
    attribute: (identifier) @name
  )
) @definition.variable

; Type annotations
(type_annotation
  (identifier) @name
) @reference.type