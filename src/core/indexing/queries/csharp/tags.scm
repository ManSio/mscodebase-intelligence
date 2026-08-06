; C# tags query — version-matched to tree-sitter-c-sharp 0.23.x

(class_declaration
  name: (_) @name
) @definition.class

(interface_declaration
  name: (_) @name
) @definition.interface

(struct_declaration
  name: (_) @name
) @definition.type

(enum_declaration
  name: (_) @name
) @definition.enum

(method_declaration
  name: (_) @name
) @definition.method

(property_declaration
  name: (_) @name
) @definition.property
