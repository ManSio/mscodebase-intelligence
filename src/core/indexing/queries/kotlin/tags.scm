; Kotlin tags query — version-matched to tree-sitter-kotlin 1.1.x
; interface в этой грамматике — модификатор class_declaration, отдельного
; узла нет (интерфейсы захватываются как классы). function/property —
; позиционный identifier (без поля name).

(class_declaration
  name: (_) @name
) @definition.class

(object_declaration
  name: (_) @name
) @definition.type

(function_declaration
  (identifier) @name
) @definition.function

(property_declaration
  (identifier) @name
) @definition.property
