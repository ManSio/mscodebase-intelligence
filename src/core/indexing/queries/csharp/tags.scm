; C# tags query

; Classes
(class_declaration
  name: (type_identifier) @name
  (#set! "kind" "class")
) @definition.class

; Interfaces
(interface_declaration
  name: (type_identifier) @name
  (#set! "kind" "interface")
) @definition.interface

; Structs
(struct_declaration
  name: (type_identifier) @name
  (#set! "kind" "struct")
) @definition.type

; Methods
(method_declaration
  name: (identifier) @name
  (#set! "kind" "method")
) @definition.method

; Properties
(property_declaration
  name: (identifier) @name
  (#set! "kind" "property")
) @definition.function

; Attributes (decorators)
(attribute
  (attribute_target)? "attribute"?
  (attribute_section
    (attribute
      name: (identifier) @name
    )
  )
  (#set! "kind" "attribute")
) @definition.decorator

; Calls
(invocation_expression
  expression: (member_access_expression
    name: (identifier) @name
  )
) @reference.call

(invocation_expression
  expression: (identifier) @name
) @reference.call

; Imports
(using_directive
  (qualified_name) @module
) @definition.import

; Variables
(variable_declaration
  (variable_declarator
    name: (identifier) @name
  )
) @definition.variable

; Fields
(field_declaration
  (variable_declarator
    name: (identifier) @name
  )
) @definition.variable