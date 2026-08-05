; Scala tags query

; Classes
(class_definition
  name: (type_identifier) @name
  (#set! "kind" "class")
) @definition.class

; Case classes
(class_definition
  modifiers: (modifiers
    (modifier) @_case
    (#eq? @_case "case")
  )
  name: (type_identifier) @name
  (#set! "kind" "class")
) @definition.class

; Traits
(trait_definition
  name: (type_identifier) @name
  (#set! "kind" "trait")
) @definition.interface

; Objects (singletons)
(object_definition
  name: (identifier) @name
  (#set! "kind" "object")
) @definition.type

; Functions
(function_definition
  name: (identifier) @name
  (#set! "kind" "function")
) @definition.function

; Methods
(method_declaration
  name: (identifier) @name
  (#set! "kind" "method")
) @definition.method

; Values and vars
(val_definition
  pattern: (identifier) @name
  (#set! "kind" "value")
) @definition.variable

(var_definition
  pattern: (identifier) @name
  (#set! "kind" "variable")
) @definition.variable

; Annotations (decorators)
(annotation
  (simple_type
    (type_identifier) @name
  )
  (#set! "kind" "annotation")
) @definition.decorator

; Calls
(apply_expression
  function: (identifier) @name
) @reference.call

(apply_expression
  function: (select_expression
    field: (identifier) @name
  )
) @reference.call

; Imports
(import_clause
  (import_selector
    (identifier) @module
  )
) @definition.import

(import_clause
  (import_selector
    (wildcard_import) @_wild
  )
) @definition.import