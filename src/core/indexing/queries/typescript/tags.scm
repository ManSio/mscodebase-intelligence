; TypeScript / TSX tags query — version-matched to tree-sitter-typescript 0.23.x

(function_declaration
  name: (_) @name
) @definition.function

(method_definition
  name: (_) @name
) @definition.method

(class_declaration
  name: (_) @name
) @definition.class

(interface_declaration
  name: (_) @name
) @definition.interface

(type_alias_declaration
  name: (_) @name
) @definition.type
