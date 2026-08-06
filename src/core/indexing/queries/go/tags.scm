; Go tags query — version-matched to tree-sitter-go 0.25.x

(function_declaration
  name: (_) @name
) @definition.function

(method_declaration
  name: (_) @name
) @definition.method

; Go типы: имя на type_spec внутри type_declaration
(type_declaration
  (type_spec
    name: (_) @name
  )
) @definition.type
