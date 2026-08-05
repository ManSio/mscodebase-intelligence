; Swift tags query

; Classes
(class_declaration
  name: (type_identifier) @name
  (#set! "kind" "class")
) @definition.class

; Structs
(struct_declaration
  name: (type_identifier) @name
  (#set! "kind" "struct")
) @definition.type

; Enums
(enum_declaration
  name: (type_identifier) @name
  (#set! "kind" "enum")
) @definition.type

; Protocols
(protocol_declaration
  name: (type_identifier) @name
  (#set! "kind" "protocol")
) @definition.interface

; Functions
(function_declaration
  name: (identifier) @name
  (#set! "kind" "function")
) @definition.function

; Methods
(method_declaration
  name: (identifier) @name
  (#set! "kind" "method")
) @definition.method

; Initializers
(initializer_declaration
  (#set! "kind" "initializer")
) @definition.function

; Properties
(property_declaration
  name: (identifier) @name
  (#set! "kind" "property")
) @definition.function

; Attributes (decorators)
(attribute
  (identifier) @name
  (#set! "kind" "attribute")
) @definition.decorator

; Calls
(function_call_expression
  called_expression: (identifier) @name
) @reference.call

(function_call_expression
  called_expression: (member_access_expression
    name: (identifier) @name
  )
) @reference.call

; Imports
(import_declaration
  (imported_modules
    (identifier) @module
  )
) @definition.import

; Variables
(pattern_binding_declaration
  (pattern
    (identifier) @name
  )
) @definition.variable