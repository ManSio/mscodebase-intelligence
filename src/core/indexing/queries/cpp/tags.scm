; C++ tags query (extends C)

; Classes
(class_specifier
  name: (type_identifier) @name
  (#set! "kind" "class")
) @definition.class

; Structs
(struct_specifier
  name: (type_identifier) @name
  (#set! "kind" "struct")
) @definition.type

; Namespaces
(namespace_definition
  name: (identifier) @name
  (#set! "kind" "namespace")
) @definition.type

; Templates
(template_declaration
  (class_specifier
    name: (type_identifier) @name
  )
) @definition.class

(template_declaration
  (function_definition
    declarator: (function_declarator
      declarator: (identifier) @name
    )
  )
) @definition.function

; Lambdas
(lambda_expression
  (#set! "kind" "function")
) @definition.function

; Using declarations
(using_declaration
  name: (scoped_identifier) @name
) @definition.import

; Inherits
(base_class_clause
  (type_identifier) @name
) @reference.type