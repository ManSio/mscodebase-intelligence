; Java tags query

; Classes
(class_declaration
  name: (identifier) @name
  (#set! "kind" "class")
) @definition.class

; Interfaces
(interface_declaration
  name: (identifier) @name
  (#set! "kind" "interface")
) @definition.interface

; Enums
(enum_declaration
  name: (identifier) @name
  (#set! "kind" "enum")
) @definition.type

; Methods
(method_declaration
  name: (identifier) @name
  (#set! "kind" "method")
) @definition.method

; Constructors
(constructor_declaration
  name: (identifier) @name
  (#set! "kind" "constructor")
) @definition.function

; Annotations (decorators equivalent)
(annotation
  (identifier) @name
  (#set! "kind" "annotation")
) @definition.decorator

; Calls
(method_invocation
  name: (identifier) @name
) @reference.call

; Field access calls
(method_invocation
  object: (_)
  name: (identifier) @name
) @reference.call

; Imports
(import_declaration
  name: (scoped_identifier) @module
) @definition.import

; Variables
(variable_declarator
  name: (identifier) @name
) @definition.variable

; Fields
(field_declaration
  (variable_declarator
    name: (identifier) @name
  )
) @definition.variable