; rules/busy-wait/rule.scm
((while_statement
    condition: (comparison_operator)
    body: (block
        (expression_statement
            (call
                function: (attribute
                            object: (identifier) @_module
                            attribute: (identifier) @_func)))))

    @busy_wait_loop)
