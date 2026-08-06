; Swift tags query — version-matched to tree-sitter-swift 0.7.x
; struct/enum в этой грамматике не имеют отдельных declaration-узлов

(class_declaration
  name: (_) @name
) @definition.class

(protocol_declaration
  name: (_) @name
) @definition.interface

(function_declaration
  name: (_) @name
) @definition.function

(typealias_declaration
  name: (_) @name
) @definition.type
