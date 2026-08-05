; Kotlin tags query

; Classes
(class_declaration
  name: (type_identifier) @name
  (#set! "kind" "class")
) @definition.class

; Data classes
(class_declaration
  modifiers: (modifiers
    (modifier) @_data
    (#eq? @_data "data")
  )
  name: (type_identifier) @name
  (#set! "kind" "class")
) @definition.class

; Interfaces
(interface_declaration
  name: (type_identifier) @name
  (#set! "kind" "interface")
) @definition.interface

; Objects (singletons)
(object_declaration
  name: (type_identifier) @name
  (#set! "kind" "object")
) @definition.type

; Functions
(function_declaration
  name: (simple_identifier) @name
  (#set! "kind" "function")
) @definition.function

; Methods (inside class)
(class_body
  (function_declaration
    name: (simple_identifier) @name
  )
  (#set! "kind" "method")
) @definition.method

; Properties
(property_declaration
  name: (simple_identifier) @name
  (#set! "kind" "property")
) @definition.function

; Annotations (decorators)
(annotation_entry
  (user_type
    type: (type_identifier) @name
  )
  (#set! "kind" "annotation")
) @definition.decorator

; Calls
(call_expression
  function: (simple_identifier) @name
) @reference.call

(call_expression
  function: (navigation_expression
    (simple_identifier) @name
  )
) @reference.call

; Imports
(import_header
  (import_alias)? (user_type
    type: (type_identifier) @module
  )
) @definition.import

; Variables
(property_declaration
  name: (simple_identifier) @name
) @definition.variable