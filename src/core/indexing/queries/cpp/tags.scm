; C++ tags query — version-matched to tree-sitter-cpp 0.23.x

(function_definition
  declarator: (function_declarator
    declarator: (_) @name
  )
) @definition.function

(class_specifier
  name: (_) @name
) @definition.class

(struct_specifier
  name: (_) @name
) @definition.type

(enum_specifier
  name: (_) @name
) @definition.type

(namespace_definition
  name: (_) @name
) @definition.namespace
