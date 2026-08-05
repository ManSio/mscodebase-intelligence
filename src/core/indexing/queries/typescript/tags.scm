; TypeScript / TSX tags query

; Functions
(function_declaration
  name: (identifier) @name
  (#set! "kind" "function")
) @definition.function

(function_expression
  name: (identifier) @name
  (#set! "kind" "function")
) @definition.function

(arrow_function
  parameters: (_)
  body: (_)
) @definition.function

; Methods
(method_definition
  name: (property_identifier) @name
  (#set! "kind" "method")
) @definition.method

; Classes
(class_declaration
  name: (type_identifier) @name
  (#set! "kind" "class")
) @definition.class

(class_expression
  name: (type_identifier) @name
) @definition.class

; Interfaces
(interface_declaration
  name: (type_identifier) @name
  (#set! "kind" "interface")
) @definition.interface

; Types
(type_alias_declaration
  name: (type_identifier) @name
  (#set! "kind" "type")
) @definition.type

; Decorators (experimental)
(decorator
  (call_expression
    function: (identifier) @name
  )
  (#set! "kind" "decorator")
) @definition.decorator

(decorator
  (identifier) @name
  (#set! "kind" "decorator")
) @definition.decorator

; Calls
(call_expression
  function: (identifier) @name
) @reference.call

(call_expression
  function: (member_expression
    property: (property_identifier) @name
  )
) @reference.call

; Imports
(import_statement
  source: (string) @module
) @definition.import

(import_clause
  (identifier) @name
) @definition.import

(namespace_import
  (identifier) @name
) @definition.import

; Variables
(variable_declarator
  name: (identifier) @name
) @definition.variable

(lexical_declaration
  (variable_declarator
    name: (identifier) @name
  )
) @definition.variable