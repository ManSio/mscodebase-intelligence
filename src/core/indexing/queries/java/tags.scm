; Java tags query — version-matched to tree-sitter-java 0.23.x

(class_declaration
  name: (_) @name
) @definition.class

(interface_declaration
  name: (_) @name
) @definition.interface

(enum_declaration
  name: (_) @name
) @definition.enum

(method_declaration
  name: (_) @name
) @definition.method

(constructor_declaration
  name: (_) @name
) @definition.constructor
