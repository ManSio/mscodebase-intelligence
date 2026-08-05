; Go tags query

; Functions
(function_declaration
  name: (identifier) @name
  (#set! "kind" "function")
) @definition.function

; Methods
(method_declaration
  receiver: (_)
  name: (identifier) @name
  (#set! "kind" "method")
) @definition.method

; Types
(type_declaration
  (type_spec
    name: (identifier) @name
  )
  (#set! "kind" "type")
) @definition.type

; Interfaces
(interface_type
  (interface_element
    name: (identifier) @name
  )
) @definition.interface

; Calls
(call_expression
  function: (identifier) @name
) @reference.call

(call_expression
  function: (selector_expression
    field: (field_identifier) @name
  )
) @reference.call

; Imports
(import_declaration
  (import_spec
    path: (interpreted_string_literal) @module
  )
) @definition.import

(import_declaration
  (import_spec_list
    (import_spec
      path: (interpreted_string_literal) @module
    )
  )
) @definition.import

; Variables
(var_declaration
  (var_spec
    name: (identifier) @name
  )
) @definition.variable

(short_var_declaration
  (identifier) @name
) @definition.variable

; Constants
(const_declaration
  (const_spec
    name: (identifier) @name
  )
) @definition.variable