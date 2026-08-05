; C tags query

; Functions
(function_definition
  declarator: (function_declarator
    declarator: (identifier) @name
  )
  (#set! "kind" "function")
) @definition.function

; Function declarations (prototypes)
(function_declaration
  declarator: (function_declarator
    declarator: (identifier) @name
  )
  (#set! "kind" "function")
) @definition.function

; Structs
(struct_specifier
  name: (type_identifier) @name
  (#set! "kind" "struct")
) @definition.type

; Enums
(enum_specifier
  name: (type_identifier) @name
  (#set! "kind" "enum")
) @definition.type

; Typedefs
(type_definition
  declarator: (init_declarator
    declarator: (identifier) @name
  )
  (#set! "kind" "type")
) @definition.type

; Calls
(call_expression
  function: (identifier) @name
) @reference.call

; Macros
(macro_definition
  name: (identifier) @name
  (#set! "kind" "macro")
) @definition.function

; Includes (imports)
(preproc_include
  path: (string_literal) @module
) @definition.import

; Variables
(init_declarator
  declarator: (identifier) @name
) @definition.variable