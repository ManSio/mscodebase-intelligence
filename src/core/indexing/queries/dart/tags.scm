; Dart tags query

; Classes
(class_declaration
  name: (type_identifier) @name
  (#set! "kind" "class")
) @definition.class

; Mixins
(mixin_declaration
  name: (type_identifier) @name
  (#set! "kind" "mixin")
) @definition.type

; Enums
(enum_declaration
  name: (type_identifier) @name
  (#set! "kind" "enum")
) @definition.type

; Extensions
(extension_declaration
  name: (type_identifier) @name
  (#set! "kind" "extension")
) @definition.type

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

; Getters/Setters
(getter_signature
  name: (identifier) @name
  (#set! "kind" "getter")
) @definition.function

(setter_signature
  name: (identifier) @name
  (#set! "kind" "setter")
) @definition.function

; Variables
(variable_declaration
  (variable_declarator
    name: (identifier) @name
  )
) @definition.variable

; Annotations (decorators)
(metadata
  (annotation
    (identifier) @name
  )
  (#set! "kind" "annotation")
) @definition.decorator

; Calls
(function_expression_invocation
  function: (identifier) @name
) @reference.call

(method_invocation
  method_name: (identifier) @name
) @reference.call

; Imports
(import_directive
  (identifier) @module
) @definition.import

(import_directive
  (uri) @module
) @definition.import