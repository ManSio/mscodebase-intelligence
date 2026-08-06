; SQL tags query — version-matched to tree-sitter-sql 0.3.x
; CREATE FUNCTION/PROCEDURE не парсятся этой грамматикой (ERROR-узел).
; Имя объекта — позиционный object_reference.

(create_table
  (object_reference) @name
) @definition.type

(create_view
  (object_reference) @name
) @definition.type

(create_index
  (object_reference) @name
) @definition.type
