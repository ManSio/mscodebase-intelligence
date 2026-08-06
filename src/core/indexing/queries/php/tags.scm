; PHP tags query — version-matched to tree-sitter-php 0.24.x

(function_definition
  name: (_) @name
) @definition.function

(method_declaration
  name: (_) @name
) @definition.method

(class_declaration
  name: (_) @name
) @definition.class

(interface_declaration
  name: (_) @name
) @definition.interface

(trait_declaration
  name: (_) @name
) @definition.trait

(enum_declaration
  name: (_) @name
) @definition.enum
