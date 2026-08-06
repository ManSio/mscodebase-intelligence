; Dart tags query — version-matched to tree-sitter-dart 0.1.x
; getter/setter парсятся как method_signature в этой грамматике

(class_definition
  name: (_) @name
) @definition.class

(mixin_declaration
  name: (_) @name
) @definition.type

(enum_declaration
  name: (_) @name
) @definition.enum

(extension_declaration
  (identifier) @name
) @definition.type

(function_signature
  name: (_) @name
) @definition.function
