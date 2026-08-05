; Rust tags query

; Functions
(function_item
  name: (identifier) @name
  (#set! "kind" "function")
) @definition.function

; Methods in impl blocks
(impl_item
  (function_item
    name: (identifier) @name
  )
  (#set! "kind" "method")
) @definition.method

; Structs
(struct_item
  name: (type_identifier) @name
  (#set! "kind" "struct")
) @definition.type

; Enums
(enum_item
  name: (type_identifier) @name
  (#set! "kind" "enum")
) @definition.type

; Traits
(trait_item
  name: (type_identifier) @name
  (#set! "kind" "trait")
) @definition.interface

; Implementations
(impl_item
  type: (type_identifier) @name
) @definition.implementation

; Macros
(macro_definition
  name: (identifier) @name
  (#set! "kind" "macro")
) @definition.function

; Calls
(call_expression
  function: (identifier) @name
) @reference.call

(call_expression
  function: (field_expression
    field: (field_identifier) @name
  )
) @reference.call

(macro_invocation
  macro: (identifier) @name
) @reference.call

; Imports
(use_declaration
  (use_tree
    (identifier) @module
  )
) @definition.import

(use_declaration
  (use_tree
    (scoped_identifier) @module
  )
) @definition.import

; Constants and statics
(const_item
  name: (identifier) @name
  (#set! "kind" "constant")
) @definition.variable

(static_item
  name: (identifier) @name
  (#set! "kind" "constant")
) @definition.variable