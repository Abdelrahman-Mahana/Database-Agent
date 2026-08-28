"use client";

/* eslint-disable react-hooks/set-state-in-effect */

import React, { useState, useMemo, useEffect, useRef, useCallback } from "react";
import { 
  Database, 
  Folder, 
  FolderOpen, 
  TableProperties, 
  Eye, 
  Terminal, 
  Layers, 
  ChevronRight, 
  ChevronDown, 
  FileCode2
} from "lucide-react";
import { SchemaTreeNode, BaseDBObject } from "@/types/api";

interface SchemaTreeViewProps {
  tree: SchemaTreeNode[];
  allObjects: BaseDBObject[];
  selectedObjectName: string | null;
  onSelectObject: (objectName: string, objectType: string) => void;
  searchQuery: string;
}

interface FlatNode {
  id: string;
  kind: string;
  name: string;
  level: number;
  hasChildren: boolean;
  isExpanded: boolean;
  isLeaf: boolean;
  objectType?: string;
  parentPath: string[];
  meta?: SchemaTreeNode["meta"];
  originalNode: SchemaTreeNode;
}

function checkNodeMatch(node: SchemaTreeNode, query: string, columnsMap: Map<string, string[]>): boolean {
  const q = query.toLowerCase();
  if (node.name.toLowerCase().includes(q)) return true;
  if (node.kind === "table" || node.kind === "view" || node.kind === "collection") {
    const cols = columnsMap.get(node.name.toLowerCase());
    if (cols && cols.some((col) => col.includes(q))) return true;
  }
  if (node.children) {
    return node.children.some((child) => checkNodeMatch(child, q, columnsMap));
  }
  return false;
}

export function SchemaTreeView({
  tree,
  allObjects,
  selectedObjectName,
  onSelectObject,
  searchQuery,
}: SchemaTreeViewProps) {
  // State for expanded node IDs
  const [expandedIds, setExpandedIds] = useState<Set<string>>(() => new Set());
  const [focusedId, setFocusedId] = useState<string | null>(null);
  const containerRef = useRef<HTMLDivElement>(null);

  // Map column names for quick column search
  const columnsByObject = useMemo(() => {
    const map = new Map<string, string[]>();
    allObjects.forEach((obj) => {
      map.set(obj.name.toLowerCase(), obj.columns.map((c) => c.name.toLowerCase()));
    });
    return map;
  }, [allObjects]);

  // Collect node IDs that must be expanded during search
  useEffect(() => {
    if (!searchQuery.trim()) return;
    const newExpanded = new Set<string>();

    const traverse = (node: SchemaTreeNode) => {
      if (node.children && node.children.length > 0) {
        if (checkNodeMatch(node, searchQuery, columnsByObject)) {
          newExpanded.add(node.id);
          node.children.forEach(traverse);
        }
      }
    };

    tree.forEach(traverse);
    setExpandedIds((prev) => new Set([...prev, ...newExpanded]));
  }, [searchQuery, tree, columnsByObject]);

  // Auto expand tree on initial load
  useEffect(() => {
    if (tree.length > 0) {
      setExpandedIds((prev) => {
        if (prev.size > 0) return prev;
        const initial = new Set<string>();
        tree.forEach((cat) => {
          initial.add(cat.id);
          if (cat.children) {
            cat.children.forEach((sch) => {
              initial.add(sch.id);
              if (sch.children) {
                sch.children.forEach((folder) => initial.add(folder.id));
              }
            });
          }
        });
        return initial;
      });
    }
  }, [tree]);

  const toggleExpand = useCallback((id: string) => {
    setExpandedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) {
        next.delete(id);
      } else {
        next.add(id);
      }
      return next;
    });
  }, []);

  // Flatten the visible hierarchy for accessibility and keyboard navigation
  const visibleFlatNodes = useMemo(() => {
    const list: FlatNode[] = [];
    const isSearching = searchQuery.trim().length > 0;

    const buildList = (node: SchemaTreeNode, level: number, parentPath: string[]) => {
      const matchesSearch = isSearching ? checkNodeMatch(node, searchQuery, columnsByObject) : true;
      if (!matchesSearch) return;

      const hasChildren = Boolean(node.children && node.children.length > 0);
      const isExpanded = expandedIds.has(node.id) || (isSearching && hasChildren);
      const isLeaf = !hasChildren;

      list.push({
        id: node.id,
        kind: node.kind,
        name: node.name,
        level,
        hasChildren,
        isExpanded,
        isLeaf,
        objectType: node.kind,
        parentPath,
        meta: node.meta,
        originalNode: node,
      });

      if (hasChildren && isExpanded && node.children) {
        node.children.forEach((child) => buildList(child, level + 1, [...parentPath, node.name]));
      }
    };

    tree.forEach((root) => buildList(root, 0, []));
    return list;
  }, [tree, expandedIds, searchQuery, columnsByObject]);

  // Keyboard navigation handler for WCAG 2.1 compliance
  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (!visibleFlatNodes.length) return;

    const currentIndex = visibleFlatNodes.findIndex((n) => n.id === focusedId);
    let targetIndex = currentIndex >= 0 ? currentIndex : 0;
    const current = visibleFlatNodes[targetIndex];

    switch (e.key) {
      case "ArrowDown":
        e.preventDefault();
        targetIndex = Math.min(currentIndex + 1, visibleFlatNodes.length - 1);
        setFocusedId(visibleFlatNodes[targetIndex].id);
        break;

      case "ArrowUp":
        e.preventDefault();
        targetIndex = Math.max(currentIndex - 1, 0);
        setFocusedId(visibleFlatNodes[targetIndex].id);
        break;

      case "ArrowRight":
        e.preventDefault();
        if (current.hasChildren) {
          if (!current.isExpanded) {
            toggleExpand(current.id);
          } else if (currentIndex + 1 < visibleFlatNodes.length) {
            setFocusedId(visibleFlatNodes[currentIndex + 1].id);
          }
        }
        break;

      case "ArrowLeft":
        e.preventDefault();
        if (current.hasChildren && current.isExpanded) {
          toggleExpand(current.id);
        } else {
          // Find parent node
          const parentNode = visibleFlatNodes.find(
            (n) => n.level === current.level - 1 && visibleFlatNodes.indexOf(n) < currentIndex
          );
          if (parentNode) {
            setFocusedId(parentNode.id);
          }
        }
        break;

      case "Enter":
      case " ":
        e.preventDefault();
        if (current) {
          if (current.isLeaf) {
            onSelectObject(current.name, current.kind);
          } else {
            toggleExpand(current.id);
          }
        }
        break;
    }
  };

  const getIcon = (kind: string, isExpanded: boolean) => {
    switch (kind) {
      case "catalog":
        return <Database className="h-4 w-4 text-primary shrink-0" />;
      case "schema":
        return <Layers className="h-4 w-4 text-sky-400 shrink-0" />;
      case "table":
        return <TableProperties className="h-3.5 w-3.5 text-emerald-400 shrink-0" />;
      case "view":
        return <Eye className="h-3.5 w-3.5 text-indigo-400 shrink-0" />;
      case "procedure":
        return <Terminal className="h-3.5 w-3.5 text-amber-400 shrink-0" />;
      case "collection":
        return <FileCode2 className="h-3.5 w-3.5 text-teal-400 shrink-0" />;
      case "folder":
      default:
        return isExpanded ? (
          <FolderOpen className="h-4 w-4 text-amber-500 shrink-0" />
        ) : (
          <Folder className="h-4 w-4 text-amber-500 shrink-0" />
        );
    }
  };

  return (
    <div
      ref={containerRef}
      role="tree"
      aria-label="Database Schema Tree"
      tabIndex={0}
      onKeyDown={handleKeyDown}
      className="outline-none focus:ring-1 focus:ring-primary/40 rounded-lg p-1 space-y-0.5"
    >
      {visibleFlatNodes.map((node) => {
        const isSelected = selectedObjectName === node.name && node.isLeaf;
        const isFocused = focusedId === node.id;
        const indentPx = node.level * 14 + 8;

        return (
          <div
            key={node.id}
            role="treeitem"
            aria-expanded={node.hasChildren ? node.isExpanded : undefined}
            aria-selected={isSelected}
            aria-label={`${node.name} (${node.kind})`}
            tabIndex={isFocused ? 0 : -1}
            onClick={() => {
              setFocusedId(node.id);
              if (node.hasChildren) {
                toggleExpand(node.id);
              } else {
                onSelectObject(node.name, node.kind);
              }
            }}
            style={{ paddingLeft: `${indentPx}px` }}
            className={`flex items-center justify-between py-1.5 pr-2 rounded-md cursor-pointer transition-colors text-xs group select-none ${
              isSelected
                ? "bg-primary/20 text-primary font-semibold border border-primary/30"
                : isFocused
                ? "bg-muted/60 text-foreground ring-1 ring-border"
                : "hover:bg-muted/40 text-foreground/90"
            }`}
          >
            <div className="flex items-center gap-1.5 min-w-0 pr-2">
              {node.hasChildren ? (
                <button
                  type="button"
                  tabIndex={-1}
                  onClick={(e) => {
                    e.stopPropagation();
                    toggleExpand(node.id);
                  }}
                  className="p-0.5 hover:bg-muted rounded text-muted-foreground shrink-0"
                >
                  {node.isExpanded ? (
                    <ChevronDown className="h-3.5 w-3.5" />
                  ) : (
                    <ChevronRight className="h-3.5 w-3.5" />
                  )}
                </button>
              ) : (
                <span className="w-3.5 shrink-0" />
              )}

              {getIcon(node.kind, node.isExpanded)}
              <span className="truncate">{node.name}</span>
            </div>

            {node.meta && (
              <div className="flex items-center gap-1 shrink-0 text-[10px] text-muted-foreground/80 font-mono">
                {node.meta.columns !== undefined && (
                  <span className="bg-muted px-1.5 py-0.2 rounded">
                    {node.meta.columns} cols
                  </span>
                )}
                {node.meta.document_count !== undefined && (
                  <span className="bg-muted px-1.5 py-0.2 rounded">
                    {node.meta.document_count} docs
                  </span>
                )}
              </div>
            )}
          </div>
        );
      })}

      {visibleFlatNodes.length === 0 && (
        <div className="p-6 text-center text-xs text-muted-foreground">
          No matching schema objects found.
        </div>
      )}
    </div>
  );
}
