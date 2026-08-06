; C tags query — version-matched to tree-sitter-c 0.24.x
; Имя функции вложено: function_definition > function_declarator > identifier

(function_definition
  declarator: (function_declarator
    declarator: (_) @name
  )
) @definition.function

(struct_specifier
  name: (_) @name
) @definition.type

(enum_specifier
  name: (_) @name
) @definition.type
